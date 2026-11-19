"""Validate/compile examples in isolation, without reading user secrets."""

import argparse
import base64
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = (
    "hvv-display.yaml",
    "hvv-cyd.yaml",
    "hvv-cyd-ha.yaml",
    "hvv-s3-ili9488.yaml",
    "hvv-direct.yaml",
)


def write_test_ca_certificate(path: Path) -> None:
    """Provide a disposable TLS CA for validating HTTPS firmware profiles."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HVV CI Test CA")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile", choices=CONFIGS, dest="firmware")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hvv-") as directory:
        target = Path(directory) / "esphome"
        shutil.copytree(
            ROOT / "esphome",
            target,
            ignore=shutil.ignore_patterns(".esphome", "secrets.yaml"),
        )
        values = yaml.safe_load((target / "secrets.example.yaml").read_text())
        values["api_encryption_key"] = base64.b64encode(
            secrets.token_bytes(32)
        ).decode()
        (target / "secrets.yaml").write_text(yaml.safe_dump(values))
        write_test_ca_certificate(target / "backend-ca.pem")
        for name in CONFIGS:
            subprocess.run(  # noqa: S603
                [sys.executable, "-m", "esphome", "config", str(target / name)],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        if args.firmware:
            subprocess.run(  # noqa: S603
                [
                    sys.executable,
                    "-m",
                    "esphome",
                    "compile",
                    str(target / args.firmware),
                ],
                check=True,
            )


if __name__ == "__main__":
    main()
