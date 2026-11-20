[CmdletBinding()]
param(
    [Alias('Profile')]
    [ValidateSet('hvv-cyd', 'hvv-cyd-ha', 'hvv-display', 'hvv-s3-ili9488', 'hvv-direct')]
    [string]$BoardProfile = 'hvv-cyd',
    [string]$VenvPath = '.venv-esphome',
    [switch]$Build,
    [switch]$Flash,
    [string]$Device,
    [string]$EspIdfPrefix = 'C:\ei'
)

$ErrorActionPreference = 'Stop'

if ($Device -and -not $Flash) {
    throw '-Device wird zusammen mit -Flash verwendet.'
}

if ($Build -and $Flash) {
    throw 'Bitte -Build oder -Flash wählen. -Flash baut die Firmware selbst.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$profileFile = Join-Path $repoRoot "esphome\$BoardProfile.yaml"
$localProfile = Join-Path $repoRoot "esphome\$BoardProfile.local.yaml"
$secretFile = Join-Path $repoRoot 'esphome\secrets.yaml'
$secretTemplate = Join-Path $repoRoot 'esphome\secrets.example.yaml'
$esphomeVersion = '2026.9.1'

if (-not (Test-Path -LiteralPath $profileFile -PathType Leaf)) {
    throw "ESPHome-Profil nicht gefunden: $profileFile"
}

$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if (-not $pythonLauncher) {
    throw 'Python 3.12 fehlt. Installiere Python 3.12 inklusive Python Launcher und starte dieses Skript erneut.'
}
& $pythonLauncher.Source -3.12 --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.12 wurde nicht gefunden. Installiere Python 3.12 inklusive Python Launcher und starte dieses Skript erneut.'
}

$venvFullPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $VenvPath))
$venvPython = Join-Path $venvFullPath 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    & $pythonLauncher.Source -3.12 -m venv $venvFullPath
    if ($LASTEXITCODE -ne 0) { throw 'Die Python-Umgebung konnte nicht erstellt werden.' }
    $venvPython = Join-Path $venvFullPath 'Scripts\python.exe'
}

$pythonMinor = & $venvPython -c 'import sys; print(str(sys.version_info[0])+chr(46)+str(sys.version_info[1]))'
if ($LASTEXITCODE -ne 0 -or $pythonMinor.Trim() -ne '3.12') {
    throw "Die Umgebung '$venvFullPath' verwendet nicht Python 3.12. Bestehende Umgebungen werden nicht überschrieben. Verwende z. B. -VenvPath .venv-esphome-312."
}

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $installedVersion = & $venvPython -c "import importlib.metadata as m; print(m.version('esphome'))" 2>$null
    $installedVersionExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($installedVersionExitCode -ne 0 -or $installedVersion.Trim() -ne $esphomeVersion) {
    & $venvPython -m pip install "esphome==$esphomeVersion"
    if ($LASTEXITCODE -ne 0) { throw "ESPHome $esphomeVersion konnte nicht installiert werden." }
}

if (-not (Test-Path -LiteralPath $localProfile -PathType Leaf)) {
    Copy-Item -LiteralPath $profileFile -Destination $localProfile
    Write-Host "Lokales Profil angelegt: $localProfile"
} else {
    Write-Host "Vorhandenes lokales Profil bleibt erhalten: $localProfile"
}

# Migrate only the transport-specific lines from previous CYD defaults. Keep
# local pin, display, and other user customizations intact.
if ($BoardProfile -eq 'hvv-cyd') {
    $localProfileText = [System.IO.File]::ReadAllText($localProfile)
    $migrationNeeded = $false
    $legacyTransport = '(?m)^([ \t]+transport:[ \t]*!include[ \t]+)packages/(?:home-assistant|https)\.yaml(?=[ \t]*(?:#|$|\r))'
    if ($localProfileText -match $legacyTransport) {
        $migrationNeeded = $true
        $localProfileText = [regex]::Replace(
            $localProfileText,
            '(?m)^[ \t]*board_entity:[ \t]*sensor\.hvv_board\r?\n',
            '')
        $localProfileText = [regex]::Replace(
            $localProfileText,
            $legacyTransport,
            '${1}packages/geofox.yaml')
    }
    if ($localProfileText -notmatch '(?m)^[ \t]*hvv_stations_json:') {
        $sourceProfileText = [System.IO.File]::ReadAllText($profileFile)
        $stationSetting = [regex]::Match(
            $sourceProfileText, '(?m)^[ \t]*hvv_stations_json:[^\r\n]*')
        $substitutionsHeader = [regex]::Match(
            $localProfileText, '(?m)^substitutions:[ \t]*\r?\n')
        if (-not $stationSetting.Success -or -not $substitutionsHeader.Success) {
            throw "Das CYD-Profil '$localProfile' kann nicht auf die Geofox-Konfiguration migriert werden."
        }
        $localProfileText = $localProfileText.Insert(
            $substitutionsHeader.Index + $substitutionsHeader.Length,
            $stationSetting.Value + [Environment]::NewLine)
        $migrationNeeded = $true
    }
    if ($migrationNeeded) {
        $backupProfile = "$localProfile.pre-esp32-geofox-backend.bak"
        if (-not (Test-Path -LiteralPath $backupProfile -PathType Leaf)) {
            Copy-Item -LiteralPath $localProfile -Destination $backupProfile
        }
        [System.IO.File]::WriteAllText(
            $localProfile, $localProfileText, [System.Text.UTF8Encoding]::new($false))
        Write-Host "CYD-Profil auf Geofox-Backend umgestellt; lokale Hardwareeinstellungen bleiben erhalten. Sicherung: $backupProfile"
    }
}

$yamlQuote = { param([string]$Value) "'" + $Value.Replace("'", "''") + "'" }
if (-not (Test-Path -LiteralPath $secretFile -PathType Leaf)) {
    $ssid = Read-Host 'WLAN-Name (SSID)'
    if ([string]::IsNullOrWhiteSpace($ssid)) { throw 'Der WLAN-Name darf nicht leer sein.' }

    $securePassword = Read-Host 'WLAN-Passwort (Eingabe bleibt verdeckt)' -AsSecureString
    $passwordPointer = [IntPtr]::Zero
    try {
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        $wifiPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    } finally {
        if ($passwordPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
        }
    }

    $randomBytes = [byte[]]::new(32)
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($randomBytes) } finally { $random.Dispose() }
    $apiKey = [Convert]::ToBase64String($randomBytes)

    $secretText = [System.IO.File]::ReadAllText($secretTemplate)
    $secretText = $secretText.Replace(
        'wifi_ssid: REPLACE_WITH_WIFI_SSID', "wifi_ssid: $(& $yamlQuote $ssid)")
    $secretText = $secretText.Replace(
        'wifi_password: REPLACE_WITH_WIFI_PASSWORD', "wifi_password: $(& $yamlQuote $wifiPassword)")
    $secretText = $secretText.Replace(
        'api_encryption_key: REPLACE_WITH_YOUR_OWN_32_BYTE_BASE64_KEY', "api_encryption_key: $apiKey")
    [System.IO.File]::WriteAllText(
        $secretFile, $secretText, [System.Text.UTF8Encoding]::new($false))
    $wifiPassword = $null
    $securePassword.Dispose()
    Write-Host "Geheimnisse angelegt: $secretFile (WLAN-Passwort wurde nicht angezeigt)"
} else {
    Write-Host "Vorhandene Geheimnisse bleiben erhalten: $secretFile (fehlende Platzhalterwerte werden danach ergänzt)"
}

$directBackendProfile = $BoardProfile -eq 'hvv-direct'
$geofoxBackendProfile = $BoardProfile -eq 'hvv-cyd'
$secretText = [System.IO.File]::ReadAllText($secretFile)
$backendUrlPlaceholder = 'https://hvv-anzeiger.local:8080/api/esphome'
$backendAuthPlaceholder = 'Bearer REPLACE_WITH_CYD_API_KEY'
$legacyBackendAuthPlaceholder = 'Basic REPLACE_WITH_BASE64_CREDENTIALS'
if ($directBackendProfile) {
    if ($secretText -notmatch '(?m)^backend_url:') {
        $secretText = $secretText.TrimEnd() + "`r`nbackend_url: $(& $yamlQuote $backendUrlPlaceholder)`r`n"
    }
    if ($secretText -notmatch '(?m)^backend_authorization:') {
        $secretText = $secretText.TrimEnd() + "`r`nbackend_authorization: $backendAuthPlaceholder`r`n"
    }
}
$secretText = [regex]::Replace(
    $secretText,
    '(?m)^backend_url:\s*["'']?https://hvv\.example\.com:8080/api/esphome["'']?\s*$',
    "backend_url: $(& $yamlQuote $backendUrlPlaceholder)")
$secretText = $secretText.Replace($legacyBackendAuthPlaceholder, $backendAuthPlaceholder)
if ($directBackendProfile -and
    ($secretText -notmatch '(?m)^backend_authorization:\s*Bearer [A-Za-z0-9_-]{32,}\s*$' -or
     -not (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $secretFile) 'backend-ca.pem')))) {
    $backendAuthorization = $null
    if ($secretText -notmatch '(?m)^backend_authorization:\s*Bearer [A-Za-z0-9_-]{32,}\s*$') {
        $secureApiKey = Read-Host 'CYD-API-Schlüssel aus der Backend-Weboberfläche > Einstellungen (Eingabe bleibt verdeckt)' -AsSecureString
        if ($secureApiKey.Length -lt 32) {
            $secureApiKey.Dispose()
            throw 'Der CYD-API-Schlüssel ist ungültig oder zu kurz.'
        }
        $passwordPointer = [IntPtr]::Zero
        try {
            $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureApiKey)
            $backendPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
        } finally {
            if ($passwordPointer -ne [IntPtr]::Zero) {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
            }
            $secureApiKey.Dispose()
        }
        $backendAuthorization = "Bearer $backendPassword"
        $backendPassword = $null
        $secretText = [regex]::Replace(
            $secretText, '(?m)^backend_authorization:.*$', "backend_authorization: $backendAuthorization")
    }
    if (-not (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $secretFile) 'backend-ca.pem'))) {
        $backendUrlMatch = [regex]::Match($secretText, '(?m)^backend_url:\s*["'']?([^"''\r\n]+)')
        if (-not $backendUrlMatch.Success) { throw 'backend_url fehlt in secrets.yaml.' }
        $backendUri = [Uri]$backendUrlMatch.Groups[1].Value.Trim()
        if ($backendUri.Scheme -ne 'https' -or $backendUri.AbsolutePath.TrimEnd('/') -ne '/api/esphome') {
            throw 'backend_url muss HTTPS verwenden und auf /api/esphome enden.'
        }
        $tcp = [System.Net.Sockets.TcpClient]::new()
        $tls = $null
        try {
            $tcp.Connect($backendUri.DnsSafeHost, $backendUri.Port)
            $acceptCertificate = [System.Net.Security.RemoteCertificateValidationCallback]{
                param($sender, $certificate, $chain, $errors)
                return $true
            }
            $tls = [System.Net.Security.SslStream]::new($tcp.GetStream(), $false, $acceptCertificate)
            $tls.AuthenticateAsClient($backendUri.DnsSafeHost)
            $remoteCertificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($tls.RemoteCertificate)
            $fingerprint = $remoteCertificate.GetCertHashString([System.Security.Cryptography.HashAlgorithmName]::SHA256)
            Write-Host "TLS-Zertifikats-Fingerabdruck: $fingerprint"
            $confirmation = Read-Host 'Stimmt er mit dem Fingerabdruck aus dem Backend-Installationsfenster überein? (ja/nein)'
            if ($confirmation -notin @('ja', 'JA', 'j', 'J')) {
                throw 'TLS-Zertifikat nicht bestätigt; Firmware-Setup abgebrochen.'
            }
            $base64 = [Convert]::ToBase64String($remoteCertificate.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert))
            $pemLines = [regex]::Matches($base64, '.{1,64}') | ForEach-Object { $_.Value }
            $pem = "-----BEGIN CERTIFICATE-----`r`n" + ($pemLines -join "`r`n") + "`r`n-----END CERTIFICATE-----`r`n"
            [System.IO.File]::WriteAllText((Join-Path (Split-Path -Parent $secretFile) 'backend-ca.pem'), $pem, [System.Text.Encoding]::ASCII)
        } finally {
            if ($tls) { $tls.Dispose() }
            $tcp.Dispose()
        }
    }
    [System.IO.File]::WriteAllText(
        $secretFile, $secretText, [System.Text.UTF8Encoding]::new($false))
    $backendAuthorization = $null
    Write-Host "CYD-Schlüssel und lokales Zertifikat in ESPHome gespeichert."
}

if ($geofoxBackendProfile) {
    foreach ($secretName in @('geofox_user_cpp', 'geofox_password_cpp')) {
        if ($secretText -notmatch "(?m)^$secretName\s*:") {
            $emptyYamlValue = $secretName + ': ' + '''""'''
            $secretText = $secretText.TrimEnd() + "`r`n" + $emptyYamlValue + "`r`n"
        }
    }
    foreach ($secretName in @('geofox_user_cpp', 'geofox_password_cpp')) {
        $emptySecretPattern = '(?m)^' + [regex]::Escape($secretName) + ':\s*''""''\s*$'
        if ($secretText -notmatch $emptySecretPattern) { continue }
        if ($secretName -eq 'geofox_user_cpp') {
            $secretValue = Read-Host 'Geofox-Benutzername'
            if ([string]::IsNullOrWhiteSpace($secretValue)) { throw 'Der Geofox-Benutzername darf nicht leer sein.' }
        } else {
            $secureGeofoxPassword = Read-Host 'Geofox-Passwort (Eingabe bleibt verdeckt)' -AsSecureString
            if ($secureGeofoxPassword.Length -eq 0) {
                $secureGeofoxPassword.Dispose()
                throw 'Das Geofox-Passwort darf nicht leer sein.'
            }
            $passwordPointer = [IntPtr]::Zero
            try {
                $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureGeofoxPassword)
                $secretValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
            } finally {
                if ($passwordPointer -ne [IntPtr]::Zero) {
                    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
                }
                $secureGeofoxPassword.Dispose()
            }
        }
        if ([string]::IsNullOrWhiteSpace($secretValue) -or $secretValue -match '[\x00-\x1f\x7f]') {
            throw 'Geofox-Zugangsdaten müssen nichtleer sein und dürfen keine Steuerzeichen enthalten.'
        }
        $cppLiteral = '"' + $secretValue.Replace('\', '\\').Replace('"', '\"') + '"'
        $yamlValue = "'" + $cppLiteral.Replace("'", "''") + "'"
        $replacement = "${secretName}: $yamlValue"
        $pattern = '(?m)^' + [regex]::Escape($secretName) + ':.*$'
        $secretText = [regex]::Replace(
            $secretText, $pattern,
            [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $replacement })
        $secretValue = $null
    }
    [System.IO.File]::WriteAllText(
        $secretFile, $secretText, [System.Text.UTF8Encoding]::new($false))
    Write-Host 'Geofox-Zugangsdaten wurden geschützt in secrets.yaml gespeichert.'
}

$requiredPlaceholders = 'REPLACE_WITH_WIFI_SSID|REPLACE_WITH_WIFI_PASSWORD|REPLACE_WITH_YOUR_OWN_32_BYTE_BASE64_KEY'
if ($secretText -match $requiredPlaceholders) {
    throw "Ersetze zuerst die Platzhalter in '$secretFile'. Die vorhandene Datei wurde nicht verändert."
}
if ($directBackendProfile -and
    $secretText -match 'REPLACE_WITH_CYD_API_KEY|REPLACE_WITH_BASE64_CREDENTIALS|hvv\.example\.com') {
    throw "Für $BoardProfile müssen backend_url und backend_authorization in '$secretFile' gesetzt werden."
}
if ($geofoxBackendProfile -and
    $secretText -match '(?m)^geofox_(?:user|password)_cpp:\s*''""''\s*$') {
    throw "Für $BoardProfile müssen Geofox-Benutzername und Passwort in '$secretFile' gesetzt sein."
}
$secretText = $null

if ($Build -or $Flash) {
    try {
        if (-not (Test-Path -LiteralPath $EspIdfPrefix -PathType Container)) {
            New-Item -ItemType Directory -Path $EspIdfPrefix -Force | Out-Null
        }
    } catch {
        throw "Der kurze ESP-IDF-Pfad '$EspIdfPrefix' ist nicht beschreibbar. Lege einen kurzen lokalen Ordner an und übergib ihn mit -EspIdfPrefix."
    }
    $env:ESPHOME_ESP_IDF_PREFIX = $EspIdfPrefix
}

$relativeLocalProfile = "esphome\$BoardProfile.local.yaml"
Push-Location $repoRoot
try {
    if ($geofoxBackendProfile) {
        & $venvPython scripts/check_cyd_secrets.py $relativeLocalProfile --esphome config
        if ($LASTEXITCODE -ne 0) { throw 'Die CYD-Konfiguration ist ungültig.' }
        if ($Build -or $Flash) {
            Write-Host 'ESPHome baut jetzt die CYD-Firmware.'
            & $venvPython scripts/check_cyd_secrets.py $relativeLocalProfile --esphome compile
            if ($LASTEXITCODE -ne 0) { throw 'Der CYD-Firmwarebau ist fehlgeschlagen.' }
        }
        if ($Flash) {
            $uploadArgs = @('upload', $relativeLocalProfile)
            if ($Device) { $uploadArgs += @('--device', $Device) }
            & $venvPython -m esphome @uploadArgs
            if ($LASTEXITCODE -ne 0) { throw 'Der Firmware-Upload ist fehlgeschlagen.' }
        }
        if (-not $Build -and -not $Flash) {
            Write-Host 'Konfiguration geprüft. Für Firmwarebau -Build, für Bau und Upload -Flash verwenden.'
        }
        return
    }

    & $venvPython -m esphome config $relativeLocalProfile
    if ($LASTEXITCODE -ne 0) { throw 'Die ESPHome-Konfiguration ist ungültig.' }

    if ($Flash) {
        Write-Host 'ESPHome baut jetzt die Firmware und fragt anschließend nach dem USB-Port.'
        $runArgs = @('run', $relativeLocalProfile)
        if ($Device) { $runArgs += @('--device', $Device) }
        & $venvPython -m esphome @runArgs
        if ($LASTEXITCODE -ne 0) { throw 'Firmwarebau oder USB-Flashen ist fehlgeschlagen.' }
    } elseif ($Build) {
        & $venvPython -m esphome compile $relativeLocalProfile
        if ($LASTEXITCODE -ne 0) { throw 'Der Firmwarebau ist fehlgeschlagen.' }
    }
} finally {
    Pop-Location
}

if (-not $Build -and -not $Flash) {
    Write-Host 'Konfiguration geprüft. Für einen Firmwarebau erneut mit -Build, für Bau und USB-Flashen mit -Flash starten.'
}
