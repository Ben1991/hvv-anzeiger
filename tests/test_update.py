import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(os.name == "nt", "requires executable POSIX shell fixtures")
class UpdateFlowTest(unittest.TestCase):
    def command(self, *args, cwd=None, check=True):
        return subprocess.run(  # noqa: S603
            args,
            cwd=cwd,
            env=self.environment,
            capture_output=True,
            text=True,
            check=check,
        )

    def script(self, path, body):
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + body)
        path.chmod(0o755)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.environment = dict(os.environ)
        self.environment.update(
            GIT_AUTHOR_NAME="Test",
            GIT_COMMITTER_NAME="Test",
            GIT_AUTHOR_EMAIL="test@example.com",
            GIT_COMMITTER_EMAIL="test@example.com",
        )
        self.remote = self.root / "remote.git"
        self.seed = self.root / "seed"
        self.checkout = self.root / "checkout"
        self.calls = self.root / "calls"
        self.command("git", "init", "--bare", "--initial-branch=main", str(self.remote))
        self.command("git", "clone", str(self.remote), str(self.seed))
        shutil.copyfile(ROOT / "update.sh", self.seed / "update.sh")
        (self.seed / "update.sh").chmod(0o755)
        for name in ("install.sh", "configure-web.sh"):
            self.script(self.seed / name, f'echo {name} >> "$HVV_UPDATE_CALLS"\n')
        self.command("git", "add", ".", cwd=self.seed)
        self.command("git", "commit", "-m", "initial", cwd=self.seed)
        self.command("git", "push", "origin", "main", cwd=self.seed)
        self.command("git", "clone", str(self.remote), str(self.checkout))
        (self.seed / "new-version").write_text("new")
        self.command("git", "add", ".", cwd=self.seed)
        self.command("git", "commit", "-m", "update", cwd=self.seed)
        self.command("git", "push", "origin", "main", cwd=self.seed)
        binary = self.root / "bin"
        binary.mkdir()
        self.script(binary / "id", 'echo "${HVV_FAKE_UID:-1000}"\n')
        self.script(
            binary / "sudo",
            'printf "%s\\n" "$*" >> "$HVV_UPDATE_CALLS"\n'
            'if [[ "${HVV_FAIL_RESTART:-0}" == 1 && "$*" == *restart* ]]; '
            'then exit 1; fi\n',
        )
        self.environment.update(
            PATH=str(binary) + os.pathsep + self.environment["PATH"],
            HVV_UPDATE_CALLS=str(self.calls),
        )

    def update(self):
        return self.command(
            str(self.checkout / "update.sh"), cwd=self.checkout, check=False
        )

    def test_real_fast_forward_then_install_and_tls_restart(self):
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.checkout / "new-version").read_text(), "new")
        self.assertEqual(
            self.calls.read_text().splitlines(),
            [
                "install.sh",
                "configure-web.sh",
                "systemctl daemon-reload",
                "systemctl enable hvv-anzeiger-web.service",
                "systemctl restart hvv-anzeiger-web.service",
                "systemctl is-active --quiet hvv-anzeiger-web.service",
            ],
        )

    def test_dirty_checkout_is_preserved_and_refused(self):
        private = self.checkout / "local-change"
        private.write_text("preserve")
        self.assertNotEqual(self.update().returncode, 0)
        self.assertEqual(private.read_text(), "preserve")
        self.assertFalse(self.calls.exists())

    def test_wrong_branch_and_root_are_refused(self):
        self.command("git", "checkout", "-b", "local", cwd=self.checkout)
        self.assertNotEqual(self.update().returncode, 0)
        self.command("git", "checkout", "main", cwd=self.checkout)
        self.environment["HVV_FAKE_UID"] = "0"
        self.assertNotEqual(self.update().returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_diverged_history_is_not_overwritten(self):
        (self.checkout / "local-version").write_text("local")
        self.command("git", "add", ".", cwd=self.checkout)
        self.command("git", "commit", "-m", "diverge", cwd=self.checkout)
        self.assertNotEqual(self.update().returncode, 0)
        self.assertEqual((self.checkout / "local-version").read_text(), "local")
        self.assertFalse(self.calls.exists())

    def test_failed_service_restart_fails_update(self):
        self.environment["HVV_FAIL_RESTART"] = "1"
        self.assertNotEqual(self.update().returncode, 0)
