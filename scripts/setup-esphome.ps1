[CmdletBinding()]
param(
    [Alias('Profile')]
    [ValidateSet('hvv-cyd', 'hvv-display', 'hvv-s3-ili9488', 'hvv-direct')]
    [string]$BoardProfile = 'hvv-cyd',
    [string]$VenvPath = '.venv-esphome',
    [switch]$Build,
    [switch]$Flash,
    [string]$EspIdfPrefix = 'C:\ei'
)

$ErrorActionPreference = 'Stop'

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

$pythonMinor = & $venvPython -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
if ($LASTEXITCODE -ne 0 -or $pythonMinor.Trim() -ne '3.12') {
    throw "Die Umgebung '$venvFullPath' verwendet nicht Python 3.12. Bestehende Umgebungen werden nicht überschrieben. Verwende z. B. -VenvPath .venv-esphome-312."
}

$installedVersion = & $venvPython -c "import importlib.metadata as m; print(m.version('esphome'))" 2>$null
if ($LASTEXITCODE -ne 0 -or $installedVersion.Trim() -ne $esphomeVersion) {
    & $venvPython -m pip install "esphome==$esphomeVersion"
    if ($LASTEXITCODE -ne 0) { throw "ESPHome $esphomeVersion konnte nicht installiert werden." }
}

if (-not (Test-Path -LiteralPath $localProfile -PathType Leaf)) {
    Copy-Item -LiteralPath $profileFile -Destination $localProfile
    Write-Host "Lokales Profil angelegt: $localProfile"
} else {
    Write-Host "Vorhandenes lokales Profil bleibt erhalten: $localProfile"
}

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

    $yamlQuote = { param([string]$Value) "'" + $Value.Replace("'", "''") + "'" }
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
    Write-Host "Vorhandene Geheimnisse bleiben unverändert: $secretFile"
}

$secretText = [System.IO.File]::ReadAllText($secretFile)
$requiredPlaceholders = 'REPLACE_WITH_WIFI_SSID|REPLACE_WITH_WIFI_PASSWORD|REPLACE_WITH_YOUR_OWN_32_BYTE_BASE64_KEY'
if ($secretText -match $requiredPlaceholders) {
    throw "Ersetze zuerst die Platzhalter in '$secretFile'. Die vorhandene Datei wurde nicht verändert."
}
if ($BoardProfile -eq 'hvv-direct' -and
    $secretText -match 'REPLACE_WITH_BASE64_CREDENTIALS|hvv\.example\.com') {
    throw "Für hvv-direct müssen backend_url und backend_authorization in '$secretFile' gesetzt werden. Die Zugangsdaten werden nicht vom Skript abgefragt."
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
    & $venvPython -m esphome config $relativeLocalProfile
    if ($LASTEXITCODE -ne 0) { throw 'Die ESPHome-Konfiguration ist ungültig.' }

    if ($Flash) {
        Write-Host 'ESPHome baut jetzt die Firmware und fragt anschließend nach dem USB-Port.'
        & $venvPython -m esphome run $relativeLocalProfile
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
