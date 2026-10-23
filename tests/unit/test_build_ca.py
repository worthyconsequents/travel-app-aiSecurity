from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from scripts.trend_aws_publish import build_secret_args


def test_optional_ca_defaults_to_no_secret_and_rejects_wrong_component(tmp_path):
    assert build_secret_args("frontend") == []
    with pytest.raises(ValueError):
        build_secret_args("python", tmp_path / "unused")
    with pytest.raises(FileNotFoundError):
        build_secret_args("frontend", tmp_path / "missing")


def test_frontend_ca_is_a_buildkit_mount_and_private_keys_are_refused(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic build CA")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "ca.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    assert build_secret_args("frontend", path) == [
        "--secret",
        "id=corporate_ca,src=" + str(path.resolve()),
    ]
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    with pytest.raises(ValueError, match="Only public CA"):
        build_secret_args("frontend", path)
