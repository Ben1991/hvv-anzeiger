import json
import os
import stat
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


class ProjectArtifactTest(unittest.TestCase):
    def test_cyd_profile_matches_supplied_2_8_inch_board(self) -> None:
        profile = (ROOT / "esphome" / "hvv-cyd.yaml").read_text(encoding="utf-8")
        ha_profile = (ROOT / "esphome" / "hvv-cyd-ha.yaml").read_text(
            encoding="utf-8"
        )
        hardware = (ROOT / "esphome" / "boards" / "cyd.yaml").read_text(
            encoding="utf-8"
        )
        guide = (ROOT / "docs" / "esp32-setup.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("display_model: ESP32-2432S028-9342", profile)
        self.assertIn("display_rotation: '0'", profile)
        self.assertIn("display_color_order: rgb", profile)
        self.assertIn("transport: !include packages/https.yaml", profile)
        self.assertIn(
            "transport: !include packages/home-assistant.yaml", ha_profile
        )
        self.assertIn("display_model: ESP32-2432S028-9342", ha_profile)
        self.assertIn("display_rotation: '0'", ha_profile)
        self.assertIn("hardware: !include boards/cyd.yaml", ha_profile)
        self.assertIn("model: ${display_model}", hardware)
        self.assertNotIn("dimensions:", hardware)
        self.assertIn("cs_pin: GPIO15", hardware)
        self.assertIn("dc_pin: GPIO2", hardware)
        self.assertIn("ESP32-2432S028", guide)
        self.assertIn("Dual-USB", guide)
        self.assertIn("ILI9342", guide)
        self.assertIn("display_rotation: '0'", guide)
        self.assertIn("display_rotation: '90'", guide)
        self.assertIn("Der resistive Touchscreen", guide)

    def test_container_departure_cache_uses_persistent_data_volume(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn("HVV_DEPARTURE_CACHE=/data/departures.json", dockerfile)
        self.assertIn("./data:/data", compose)

    def test_readme_has_open_source_user_journey(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        headings = [
            line
            for line in readme.splitlines()
            if line.startswith("## ") and not line.startswith("### ")
        ]
        self.assertEqual(
            headings,
            [
                "## Inhalt",
                "## Wieso gibt es dieses Projekt?",
                "## Und wie funktioniert es?",
                "## Funktionen",
                "## Praxisbeispiel",
                "## Vorkonfigurierte Anzeige",
                "## Voraussetzungen",
                "## Geofox-Zugang beantragen",
                "## Display anschließen",
                "## Installieren",
                "## Konfigurieren",
                "## Betrieb und Updates",
                "## Fehlerverhalten und Diagnose",
                "## Ressourcen- und Stromverbrauch",
                "## Sicherheit und Datenschutz",
                "## Projektentwicklung",
                "## Grenzen",
                "## Release Notes",
                "## Haftungsausschluss",
                "## Lizenz und Unterstützung",
            ],
        )
        self.assertIn(
            "https://github.com/Ben1991/hvv-anzeiger/issues",
            readme,
        )

    def test_readme_screenshot_exists_with_display_dimensions(self) -> None:
        screenshot = ROOT / "docs" / "hvv-anzeiger-preview.png"
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/hvv-anzeiger-preview.png", readme)
        with Image.open(screenshot) as image:
            self.assertEqual(image.size, (320, 240))

    def test_readme_documents_geofox_access_and_project_support(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://gti.geofox.de/", readme)
        self.assertIn(
            "https://www.hvv.de/de/fahrplaene/abruf-fahrplaninfos/datenabruf",
            readme,
        )
        self.assertIn("Der Antrag erfolgt so:", readme)
        self.assertIn("Eine mögliche Beschreibung für den Antrag:", readme)
        self.assertIn("Die HOCHBAHN stellt die GTI-Schnittstelle", readme)
        self.assertNotIn(
            "Geofox beziehungsweise die Schnittstelle wird von der HBT",
            readme,
        )
        self.assertIn("https://gti.geofox.de/html/GTIHandbuch_p.html", readme)
        self.assertIn("https://ko-fi.com/bema1991", readme)
        self.assertIn("## Haftungsausschluss", readme)
        self.assertIn("keine Rechtsberatung", readme)

    def test_readme_defines_supported_os_and_raspberry_pi_models(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")

        for expected in (
            "Raspberry Pi OS Lite, 64 Bit, Trixie",
            "Raspberry Pi OS Lite, 32 Bit, Trixie",
            "Raspberry Pi Zero 2 W",
            "Raspberry Pi 3A+, 3B und 3B+",
            "Raspberry Pi 4B und Raspberry Pi 400",
            "Raspberry Pi Zero, Zero W und Raspberry Pi 1",
            "Raspberry Pi 5, 500, 500+ und Compute Module 5",
            "kompatibel by design",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, readme)

        self.assertIn(
            "Raspberry Pi OS (Lite oder Desktop)",
            installer,
        )
        self.assertIn(
            "| Raspberry Pi OS Legacy Lite, 64 oder 32 Bit, Bookworm | "
            "nicht unterstützt",
            readme,
        )
        self.assertIn("sys.version_info < (3, 13)", installer)
        self.assertIn("Python 3.13 oder neuer ist erforderlich", installer)
        self.assertIn(
            "sudo -H python3 -c 'import sys; "
            "raise SystemExit(sys.version_info < (3, 13))'",
            installer,
        )
        self.assertNotIn("Raspberry Pi OS/Debian", installer)

    def test_supported_python_uses_system_gpio_compatibility(self) -> None:
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")

        self.assertIn('requires-python = ">=3.13"', project)
        self.assertNotIn("rpi-gpio==", requirements)
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('python-version: ["3.13", "3.15.2"]', workflow)
        self.assertIn("python3-rpi-lgpio", installer)
        self.assertIn("venv --system-site-packages", installer)

    def test_station_adjustment_skill_is_complete(self) -> None:
        skill = ROOT / ".agents" / "skills" / "adjust-hvv-stations"
        instructions = (skill / "SKILL.md").read_text(encoding="utf-8")
        metadata = (skill / "agents" / "openai.yaml").read_text(encoding="utf-8")
        script = skill / "scripts" / "update_stations.py"
        self.assertIn("name: adjust-hvv-stations", instructions)
        self.assertIn("--stations-file", instructions)
        self.assertIn("config.example.json", instructions)
        self.assertIn("/opt/hvv-anzeiger/config.json", instructions)
        self.assertIn("$adjust-hvv-stations", metadata)
        self.assertTrue(script.is_file())

    def test_security_and_contribution_policies_are_present(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        codeowners = (ROOT / ".github" / "CODEOWNERS").read_text(
            encoding="utf-8"
        )
        self.assertIn("[SECURITY.md](SECURITY.md)", readme)
        self.assertIn("[CONTRIBUTING.md](CONTRIBUTING.md)", readme)
        self.assertIn("/security/advisories/new", security)
        self.assertIn("Keine echten Geofox-Zugangsdaten", security)
        self.assertIn("Pull Request", contributing)
        self.assertIn("Niemals direkt auf `main`", contributing)
        self.assertIn("100 Prozent", contributing)
        self.assertIn("GPL-3.0-only", contributing)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", license_text)
        self.assertIn("Version 3, 29 June 2007", license_text)
        self.assertIn("[GNU General Public License Version 3](LICENSE)", readme)
        self.assertEqual(codeowners.strip().splitlines()[-1], "* @Ben1991")

    def test_pull_request_template_covers_review_context(self) -> None:
        template = (
            ROOT / ".github" / "pull_request_template.md"
        ).read_text(encoding="utf-8")
        expected_sections = (
            "## Ticket / Referenz",
            "## Kontext",
            "## Änderungen",
            "## Produktwirkung",
            "## Risiken und Grenzen",
            "## Verifikation",
            "## Screenshots oder Beispiele",
            "## Offene Punkte",
            "## Review-Hinweise",
        )
        positions = [template.index(section) for section in expected_sections]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("- [ ] Tests", template)
        self.assertIn("- [ ] Coverage", template)
        self.assertIn(
            "This change has been created with the support of Codex.",
            template,
        )

    def test_installer_is_executable_and_syntax_is_checked_by_ci(self) -> None:
        installer = ROOT / "install.sh"
        mode = installer.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)
        self.assertTrue(os.access(installer, os.X_OK))
        diagnostic = ROOT / "diagnose.sh"
        self.assertTrue(diagnostic.stat().st_mode & stat.S_IXUSR)
        self.assertTrue(os.access(diagnostic, os.X_OK))
        credentials = ROOT / "configure-credentials.sh"
        self.assertTrue(credentials.stat().st_mode & stat.S_IXUSR)
        self.assertTrue(os.access(credentials, os.X_OK))
        web_configuration = ROOT / "configure-web.sh"
        self.assertTrue(web_configuration.stat().st_mode & stat.S_IXUSR)
        self.assertTrue(os.access(web_configuration, os.X_OK))
        web_configuration_text = web_configuration.read_text(encoding="utf-8")
        self.assertIn("ip -4 route get 1.1.1.1", web_configuration_text)
        self.assertIn("hostname -I", web_configuration_text)
        self.assertIn('CERT_FILE="${HVV_WEB_CERTFILE:', web_configuration_text)
        self.assertIn('KEY_FILE="${HVV_WEB_KEYFILE:', web_configuration_text)
        self.assertIn("https://%s:8080/", web_configuration_text)
        smoke_test = ROOT / "tests" / "install-smoke.sh"
        self.assertTrue(smoke_test.stat().st_mode & stat.S_IXUSR)
        self.assertTrue(os.access(smoke_test, os.X_OK))
        installer_text = installer.read_text(encoding="utf-8")
        self.assertIn('systemctl stop "$SERVICE_NAME"', installer_text)
        self.assertIn('enable --now "$LOG_CLEANUP_TIMER"', installer_text)
        self.assertIn('enable "$WEB_SERVICE"', installer_text)
        self.assertIn('restart "$WEB_SERVICE"', installer_text)
        self.assertIn('is-active --quiet "$WEB_SERVICE"', installer_text)
        self.assertIn('APP_USER="hvv-anzeiger"', installer_text)
        self.assertIn('systemctl enable "$SERVICE_NAME"', installer_text)
        self.assertIn("--require-hashes", installer_text)
        self.assertNotIn("pip\" install --upgrade pip", installer_text)
        self.assertIn('chown -R root:root "$STAGING_DIR"', installer_text)
        self.assertIn(
            'chown -R "$APP_USER:$APP_GROUP" "$STAGING_DIR/var"', installer_text
        )
        self.assertIn("BACKUP_DIR", installer_text)
        self.assertIn("restore_units", installer_text)
        self.assertIn("INSTALL_SUCCEEDED", installer_text)
        self.assertIn('sudo install -m 0755 \\', installer_text)
        self.assertIn('"$SOURCE_DIR/configure-credentials.sh"', installer_text)
        self.assertIn('"$SOURCE_DIR/configure-web.sh"', installer_text)
        self.assertIn("openssl", installer_text)
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("tests/install-smoke.sh", workflow)
        update_script = (ROOT / "update.sh").read_text(encoding="utf-8")
        self.assertIn('"$SCRIPT_DIR/configure-web.sh"', update_script)
        self.assertIn('systemctl daemon-reload', update_script)
        self.assertIn('systemctl restart "$WEB_SERVICE"', update_script)
        self.assertIn('systemctl is-active --quiet "$WEB_SERVICE"', update_script)

    def test_systemd_service_uses_protected_environment_file(self) -> None:
        service = (ROOT / "systemd" / "hvv-anzeiger.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("EnvironmentFile=/etc/hvv-anzeiger.env", service)
        self.assertIn("Environment=HVV_WIFI_INTERFACE=wlan0", service)
        self.assertIn("Restart=always", service)
        self.assertIn("Type=notify", service)
        self.assertIn("WatchdogSec=90s", service)
        self.assertIn("StartLimitIntervalSec=0", service)
        self.assertIn("TimeoutStopSec=10", service)
        self.assertIn("After=network.target", service)
        self.assertNotIn("network-online.target", service)
        self.assertNotIn("time-sync.target", service)
        self.assertIn("WantedBy=multi-user.target", service)
        self.assertIn("NoNewPrivileges=true", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ProtectHome=true", service)
        self.assertIn("ReadWritePaths=/opt/hvv-anzeiger/var", service)
        self.assertIn("User=hvv-anzeiger", service)
        self.assertIn("Group=hvv-anzeiger", service)
        self.assertIn("WorkingDirectory=/opt/hvv-anzeiger/var", service)
        self.assertIn(
            "--cache /opt/hvv-anzeiger/var/stations.json",
            service,
        )
        self.assertIn(
            "--departure-cache /opt/hvv-anzeiger/var/departures.json",
            service,
        )
        self.assertNotIn("GEOFOX_PASSWORD=", service)

        web_service = (ROOT / "systemd" / "hvv-anzeiger-web.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("--host 0.0.0.0", web_service)
        self.assertIn("After=network.target", web_service)
        self.assertNotIn("network-online.target", web_service)
        self.assertNotIn("time-sync.target", web_service)
        self.assertIn("StartLimitIntervalSec=0", web_service)
        self.assertIn("Restart=always", web_service)
        self.assertIn("TimeoutStopSec=10", web_service)
        self.assertIn("--tls-certfile /etc/hvv-anzeiger/web.crt", web_service)
        self.assertIn("--tls-keyfile /etc/hvv-anzeiger/web.key", web_service)
        self.assertIn(
            "--departure-cache /opt/hvv-anzeiger/var/departures.json",
            web_service,
        )
        self.assertIn("EnvironmentFile=-/opt/hvv-anzeiger/var/web.env", web_service)
        self.assertIn(
            "Environment=HVV_WEB_ENV_FILE=/opt/hvv-anzeiger/var/web.env",
            web_service,
        )

    def test_dependencies_are_locked_with_hashes_and_audited_in_ci(self) -> None:
        for filename in (
            "requirements.txt",
            "requirements-dev.txt",
            "requirements-container.txt",
        ):
            with self.subTest(filename=filename):
                lines = (ROOT / filename).read_text(encoding="utf-8").splitlines()
                requirements = [
                    (index, line)
                    for index, line in enumerate(lines)
                    if line and not line.startswith((" ", "#"))
                ]
                self.assertTrue(requirements)
                for index, requirement in requirements:
                    self.assertIn("==", requirement)
                    self.assertTrue(requirement.endswith("\\"))
                    self.assertTrue(
                        lines[index + 1].lstrip().startswith("--hash=sha256:")
                    )

        runtime_lock = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("pillow==13.0.0", runtime_lock)
        container_lock = (ROOT / "requirements-container.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("pillow==13.0.0", container_lock)
        self.assertIn("tzdata==2026.5", container_lock)
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("pip-audit --requirement requirements.txt", workflow)
        self.assertIn("pip-audit --requirement requirements-container.txt", workflow)
        self.assertIn("--require-hashes --requirement requirements-dev.txt", workflow)

    def test_weekly_log_cleanup_has_retention_and_size_limits(self) -> None:
        cleanup = (
            ROOT / "systemd" / "hvv-anzeiger-log-cleanup.service"
        ).read_text(encoding="utf-8")
        timer = (ROOT / "systemd" / "hvv-anzeiger-log-cleanup.timer").read_text(
            encoding="utf-8"
        )
        diagnostic = (ROOT / "diagnose.sh").read_text(encoding="utf-8")
        self.assertIn("journalctl --rotate", cleanup)
        self.assertIn("--vacuum-time=7d", cleanup)
        self.assertIn("--vacuum-size=100M", cleanup)
        self.assertIn("OnCalendar=weekly", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("hvv-anzeiger-log-cleanup.timer", diagnostic)
        self.assertIn('credential_present "GEOFOX_USER"', diagnostic)
        self.assertIn('credential_present "GEOFOX_PASSWORD"', diagnostic)
        self.assertIn("load_config", diagnostic)
        self.assertIn("--property=Restart", diagnostic)
        self.assertIn("WatchdogUSec", diagnostic)

    def test_readme_documents_every_example_configuration_field(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        config = json.loads(
            (ROOT / "config.example.json").read_text(encoding="utf-8")
        )
        fields = [
            *(f"api.{field}" for field in config["api"]),
            *(f"display.{field}" for field in config["display"]),
            *(f"night_shutdown.{field}" for field in config["night_shutdown"]),
            *(f"stations[].{field}" for field in config["stations"][0]),
            *(
                f"stations[].routes[].{field}"
                for field in config["stations"][0]["routes"][0]
            ),
        ]
        for field in fields:
            with self.subTest(field=field):
                self.assertIn(f"`{field}`", readme)

    def test_readme_documents_cyd_firmware_flash_steps(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("ESP32 Schritt für Schritt", readme)
        self.assertIn("scripts\\setup-esphome.ps1 -Profile hvv-cyd", readme)
        self.assertIn("scripts\\setup-esphome.ps1 -Profile hvv-cyd -Flash", readme)
        self.assertIn("docs/esp32-setup.md", readme)

    def test_esp32_guides_give_beginner_steps_and_recovery_actions(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "esp32-setup.md").read_text(
            encoding="utf-8"
        )

        for instruction in (
            "PowerShell öffnen",
            "git --version",
            "py -3.12 --version",
            "git clone https://github.com/Ben1991/hvv-anzeiger.git",
            "Schritt 4: ESPHome und das CYD-Profil einrichten",
            "keinen automatischen Fallback zu Home Assistant",
            "vom CYD aus per DNS auflösbar",
            "Wenn kein COM-Port angeboten wird",
            "Wenn keine Abfahrten erscheinen",
            "Wenn der Bildschirm leer bleibt oder Farben falsch sind",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, readme + guide)

    def test_esp32_setup_script_preserves_existing_local_configuration(self) -> None:
        script = (ROOT / "scripts" / "setup-esphome.ps1").read_text(
            encoding="utf-8"
        )
        guide = (ROOT / "docs" / "esp32-setup.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("esphomeVersion = '2026.9.1'", script)
        self.assertIn("[string]$BoardProfile = 'hvv-cyd'", script)
        self.assertIn(
            "print(str(sys.version_info[0])+chr(46)+str(sys.version_info[1]))",
            script,
        )
        self.assertIn("if (-not (Test-Path -LiteralPath $localProfile", script)
        self.assertIn("if (-not (Test-Path -LiteralPath $secretFile", script)
        self.assertIn("SecureStringToBSTR", script)
        self.assertIn("RandomNumberGenerator", script)
        self.assertIn("ESPHOME_ESP_IDF_PREFIX", script)
        self.assertIn("$previousErrorActionPreference = $ErrorActionPreference", script)
        self.assertIn("$ErrorActionPreference = 'Continue'", script)
        self.assertIn("hvv-cyd-ha", script)
        self.assertIn(
            "$directBackendProfile = $BoardProfile -in @('hvv-cyd', 'hvv-direct')",
            script,
        )
        self.assertIn("Webpasswort des Hintergrunddienstes", script)
        self.assertIn(
            '$backendAuthPlaceholder, "Basic $backendAuthorization")', script
        )
        self.assertIn("packages/home-assistant\\.yaml", script)
        self.assertIn(".pre-direct-backend.bak", script)
        self.assertIn("$secretText -notmatch '(?m)^backend_url:'", script)
        self.assertIn(
            "$secretText -notmatch '(?m)^backend_authorization:'", script
        )
        self.assertIn(
            "backendUri.AbsolutePath.TrimEnd('/') -ne '/api/esphome'", script
        )
        self.assertIn("-m esphome run", script)
        self.assertIn("cp esphome/hvv-cyd.yaml esphome/hvv-cyd.local.yaml", guide)
        self.assertIn("esphome config esphome/hvv-cyd.local.yaml", guide)
        self.assertNotIn("esphome/hvv-display.local.yaml", guide)
        self.assertIn(
            "powershell -NoProfile -ExecutionPolicy Bypass -File "
            ".\\scripts\\setup-esphome.ps1 -Profile hvv-cyd -Flash",
            guide,
        )

    def test_home_assistant_and_esp32_guides_have_separate_scope(self) -> None:
        home_assistant = (ROOT / "docs" / "home-assistant.md").read_text(
            encoding="utf-8"
        )
        esp32 = (ROOT / "docs" / "esp32-setup.md").read_text(encoding="utf-8")

        self.assertIn("HA-Paketintegration", home_assistant)
        self.assertIn("ESP32-Einrichtungsanleitung", home_assistant)
        self.assertIn("Windows: CYD einrichten und flashen", esp32)
        self.assertIn("Firmware aktualisieren", esp32)
        self.assertIn("Home Assistant ist dafür nicht", esp32)
        self.assertIn("hvv-cyd-ha", esp32)


if __name__ == "__main__":
    unittest.main()
