import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hvv_display.web import hash_web_password, verify_web_password

ROOT = Path(__file__).resolve().parents[1]
CONFIGURE = ROOT / "configure-credentials.sh"


class CredentialConfigurationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.env_file = self.directory / "hvv-anzeiger.env"
        fake_bin = self.directory / "bin"
        fake_bin.mkdir()
        sudo = fake_bin / "sudo"
        sudo.write_text(
            """#!/bin/sh
if [ "$1" = "chown" ]; then
  exit 0
fi
if [ "$1" = "install" ]; then
  shift
  set -- "$1" "$2" "$7" "$8"
  exec install "$@"
fi
exec "$@"
""",
            encoding="utf-8",
        )
        sudo.chmod(0o755)
        self.environment = {
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "HVV_ENV_FILE": str(self.env_file),
        }

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_configure(
        self, user_input: str, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [str(CONFIGURE), *arguments],
            input=user_input,
            text=True,
            capture_output=True,
            env=self.environment,
            check=False,
        )

    def test_first_run_prompts_and_stores_credentials_securely(self) -> None:
        result = self.run_configure('application-id\npa"ss\\word$42\n')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.env_file.read_text(encoding="utf-8"),
            'GEOFOX_USER="application-id"\nGEOFOX_PASSWORD="pa\\"ss\\\\word\\$42"\n',
        )
        self.assertEqual(stat.S_IMODE(self.env_file.stat().st_mode), 0o600)
        self.assertNotIn('pa"ss\\word$42', result.stdout + result.stderr)
        self.assertIn("gespeichert", result.stdout)
        loaded = subprocess.run(  # noqa: S603
            [
                "/bin/bash",
                "-c",
                '. "$1"; printf "%s\\n%s\\n" "$GEOFOX_USER" "$GEOFOX_PASSWORD"',
                "bash",
                str(self.env_file),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(loaded.returncode, 0, loaded.stderr)
        self.assertEqual(loaded.stdout, 'application-id\npa"ss\\word$42\n')

    def test_existing_complete_credentials_are_kept_without_prompt(self) -> None:
        original = 'GEOFOX_USER="old-user"\nGEOFOX_PASSWORD="old-password"\n'
        self.env_file.write_text(original, encoding="utf-8")
        self.env_file.chmod(0o644)

        result = self.run_configure("")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.env_file.read_text(encoding="utf-8"), original)
        self.assertEqual(stat.S_IMODE(self.env_file.stat().st_mode), 0o600)
        self.assertIn("bereits vollständig", result.stdout)

    def test_force_replaces_credentials_and_empty_values_are_reprompted(self) -> None:
        self.env_file.write_text(
            'GEOFOX_USER="old-user"\nGEOFOX_PASSWORD="old-password"\n',
            encoding="utf-8",
        )

        result = self.run_configure(
            "\nnew-user\n   \nnew-password\n",
            "--force",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.env_file.read_text(encoding="utf-8"),
            'GEOFOX_USER="new-user"\nGEOFOX_PASSWORD="new-password"\n',
        )
        self.assertEqual(result.stderr.count("darf nicht leer sein"), 2)

    def test_incomplete_credentials_require_new_input(self) -> None:
        self.env_file.write_text(
            'GEOFOX_USER="old-user"\nGEOFOX_PASSWORD=""\n',
            encoding="utf-8",
        )

        result = self.run_configure("new-user\nnew-password\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GEOFOX_USER="new-user"', self.env_file.read_text())

    def test_aborted_input_and_unknown_option_fail_safely(self) -> None:
        aborted = self.run_configure("")
        unknown = self.run_configure("", "--unknown")

        self.assertNotEqual(aborted.returncode, 0)
        self.assertIn("abgebrochen", aborted.stderr)
        self.assertFalse(self.env_file.exists())
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("Unbekannte Option", unknown.stderr)

    def test_aborted_reconfiguration_keeps_existing_file(self) -> None:
        original = 'GEOFOX_USER="old-user"\nGEOFOX_PASSWORD=""\n'
        self.env_file.write_text(original, encoding="utf-8")

        result = self.run_configure("")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.env_file.read_text(encoding="utf-8"), original)
        self.assertEqual(list(self.directory.glob("hvv-anzeiger.env.tmp.*")), [])


@unittest.skipUnless(os.name == "posix", "Linux web provisioning script")
class WebPasswordConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.env_file = self.directory / "web.env"
        fake_bin = self.directory / "bin"
        fake_bin.mkdir()
        sudo = fake_bin / "sudo"
        sudo.write_text("""#!/bin/bash
if [[ "$1" == chown ]]; then exit 0; fi
if [[ "$1" == install ]]; then
  shift
  args=()
  while (($#)); do
    case "$1" in
      -o|-g) shift 2 ;;
      *) args+=("$1"); shift ;;
    esac
  done
  exec install "${args[@]}"
fi
exec "$@"
""")
        (fake_bin / "getent").write_text("#!/bin/sh\nexit 0\n")
        (fake_bin / "ip").write_text(
            "#!/bin/sh\necho '1.1.1.1 dev wlan0 src 192.0.2.10'\n"
        )
        (fake_bin / "openssl").write_text(
            "#!/bin/sh\necho 'IP Address:192.0.2.10, DNS:hvv-anzeiger.local'\n"
        )
        (fake_bin / "hostnamectl").write_text("#!/bin/sh\nexit 0\n")
        (fake_bin / "systemctl").write_text("#!/bin/sh\nexit 0\n")
        for executable in fake_bin.iterdir():
            executable.chmod(0o755)
        app = self.directory / "app"
        (app / ".venv/bin").mkdir(parents=True)
        (app / ".venv/bin/python").symlink_to(sys.executable)
        cert_dir = self.directory / "certificates"
        cert_dir.mkdir()
        (cert_dir / "web.crt").write_text("test certificate")
        avahi_config = self.directory / "avahi-daemon.conf"
        avahi_config.write_text("[server]\n#host-name=old-name\n")
        self.environment = {
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "HVV_APP_DIR": str(app),
            "HVV_WEB_ENV_FILE": str(self.env_file),
            "HVV_WEB_CERT_DIR": str(cert_dir),
            "HVV_AVAHI_CONFIG": str(avahi_config),
        }

    def run_configure(self, user_input, *arguments):
        return subprocess.run(  # noqa: S603
            [str(ROOT / "configure-web.sh"), *arguments],
            input=user_input,
            text=True,
            capture_output=True,
            env=self.environment,
            check=False,
        )

    def encoded_password(self):
        for line in self.env_file.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key == "HVV_WEB_PASSWORD_HASH":
                return value.strip().strip('"')
        self.fail("Webpasswort-Hash fehlt in web.env")

    def test_first_run_sets_bootstrap_password_and_random_device_key(self):
        result = self.run_configure("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(verify_web_password("hvv-anzeiger", self.encoded_password()))
        values = dict(
            line.split("=", 1)
            for line in self.env_file.read_text().splitlines()
            if "=" in line
        )
        self.assertEqual(values["HVV_WEB_PASSWORD_MUST_CHANGE"], '"1"')
        self.assertGreaterEqual(len(values["HVV_ESPHOME_API_TOKEN"].strip('"')), 40)
        self.assertNotIn(values["HVV_ESPHOME_API_TOKEN"], result.stdout + result.stderr)
        avahi_config = self.directory / "avahi-daemon.conf"
        self.assertIn("host-name=hvv-anzeiger", avahi_config.read_text())
        self.assertEqual(stat.S_IMODE(self.env_file.stat().st_mode), 0o600)

    def test_existing_complete_credentials_are_kept_without_prompt(self):
        encoded = hash_web_password("existing-individual-password")
        original = f'HVV_WEB_PASSWORD_HASH="{encoded}"\n'
        self.env_file.write_text(original)
        result = self.run_configure("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(original.strip(), self.env_file.read_text())
        self.assertIn("HVV_ESPHOME_API_TOKEN", self.env_file.read_text())

    def test_old_shared_default_is_marked_for_forced_rotation(self):
        encoded = hash_web_password("hvv-anzeiger")
        self.env_file.write_text(f'HVV_WEB_PASSWORD_HASH="{encoded}"\n')
        result = self.run_configure("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(verify_web_password("hvv-anzeiger", self.encoded_password()))
        self.assertIn('HVV_WEB_PASSWORD_MUST_CHANGE="1"', self.env_file.read_text())

    def test_incomplete_credentials_are_replaced_by_bootstrap_credentials(self):
        self.env_file.write_text('HVV_WEB_PASSWORD_HASH=""\n')
        result = self.run_configure("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(verify_web_password("hvv-anzeiger", self.encoded_password()))

    def test_first_run_needs_no_input_and_unknown_option_fails(self):
        result = self.run_configure("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(verify_web_password("hvv-anzeiger", self.encoded_password()))
        self.assertIn('HVV_WEB_PASSWORD_MUST_CHANGE="1"', self.env_file.read_text())
        result = self.run_configure("", "--unknown")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
