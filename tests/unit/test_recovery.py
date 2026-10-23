import json

import pytest
from botocore.exceptions import ClientError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scripts import trend_recovery as recovery
from scripts.trend_aws_config import TrendAWSConfig


def test_encrypted_roundtrip_authenticates_deployment_and_tamper():
    key = AESGCM.generate_key(bit_length=256)
    files = {"private/secret.json": b'{"password":"synthetic-only"}', "source/main.py": b"pass\n"}
    blob = recovery.encrypt_files(files, key, "deployment-a")
    assert b"synthetic-only" not in blob
    assert recovery.decrypt_files(blob, key, "deployment-a") == files
    for candidate, candidate_key, deployment in (
        (blob[:-1] + bytes([blob[-1] ^ 1]), key, "deployment-a"),
        (blob, AESGCM.generate_key(bit_length=256), "deployment-a"),
        (blob, key, "deployment-b"),
    ):
        with pytest.raises(InvalidTag):
            recovery.decrypt_files(candidate, candidate_key, deployment)


@pytest.mark.parametrize("name", ["../secret", "/absolute", "a/../../secret", r"..\secret", ""])
def test_archive_rejects_path_escape(name):
    with pytest.raises(ValueError):
        recovery.safe_path(name)


def test_clean_export_removes_stale_runtime_ids_and_keeps_nodeport():
    raw = {
        "kind": "Service",
        "metadata": {
            "name": "edge",
            "uid": "old",
            "resourceVersion": "old",
            "managedFields": [],
            "finalizers": ["old"],
        },
        "status": {"loadBalancer": {}},
        "spec": {
            "clusterIP": "172.20.1.2",
            "clusterIPs": ["172.20.1.2"],
            "ports": [{"nodePort": 32080, "port": 8080}],
        },
    }
    clean = recovery.clean_object(raw)
    assert clean["metadata"] == {"name": "edge"}
    assert "status" not in clean and "clusterIP" not in clean["spec"]
    assert clean["spec"]["ports"][0]["nodePort"] == 32080
    assert raw["metadata"]["uid"] == "old"


@pytest.mark.parametrize("missing_tags", [False, True])
def test_existing_unowned_or_untagged_bucket_never_recreated(missing_tags):
    c = TrendAWSConfig.load("infra/trend-aws/trend.example.env")

    class S3:
        def head_bucket(self, **kw):
            pass

        def get_bucket_tagging(self, **kw):
            if missing_tags:
                raise ClientError(
                    {
                        "Error": {"Code": "NoSuchTagSet"},
                        "ResponseMetadata": {"HTTPStatusCode": 404},
                    },
                    "GetBucketTagging",
                )
            return {"TagSet": [{"Key": "Deployment", "Value": "other"}]}

        def create_bucket(self, **kw):
            pytest.fail("Never recreate unowned bucket")

    with pytest.raises((ValueError, ClientError)):
        recovery.ensure_bucket(c, S3())


def test_new_bucket_has_blocked_public_access_encryption_versioning_tls_and_ownership():
    c = TrendAWSConfig.load("infra/trend-aws/trend.example.env")
    events = {}

    class S3:
        def head_bucket(self, **kw):
            raise ClientError(
                {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadBucket",
            )

        def __getattr__(self, name):
            return lambda **kw: events.update({name: kw})

    name = recovery.ensure_bucket(c, S3())
    assert name.startswith("dannytran-")
    assert all(events["put_public_access_block"]["PublicAccessBlockConfiguration"].values())
    assert events["put_bucket_versioning"]["VersioningConfiguration"]["Status"] == "Enabled"
    assert (
        events["put_bucket_encryption"]["ServerSideEncryptionConfiguration"]["Rules"][0][
            "ApplyServerSideEncryptionByDefault"
        ]["SSEAlgorithm"]
        == "AES256"
    )
    statement = json.loads(events["put_bucket_policy"]["Policy"])["Statement"][0]
    assert (
        statement["Effect"] == "Deny"
        and statement["Condition"]["Bool"]["aws:SecureTransport"] == "false"
    )


def test_verify_cli_needs_no_aws_credentials_or_env_file(tmp_path, monkeypatch, capsys):
    import base64

    key = AESGCM.generate_key(bit_length=256)
    archive = tmp_path / "recovery.aesgcm"
    archive.write_bytes(recovery.encrypt_files({"a.txt": b"a"}, key, "known-deployment"))
    keyfile = tmp_path / "key"
    recovery.private_write(keyfile, base64.b64encode(key))
    monkeypatch.setattr(
        "sys.argv",
        [
            "trend_recovery",
            "verify",
            "--deployment",
            "known-deployment",
            "--archive",
            str(archive),
            "--key-file",
            str(keyfile),
        ],
    )
    monkeypatch.setattr(recovery, "AWS", lambda *a: pytest.fail("No AWS for offline verification"))
    recovery.main()
    assert json.loads(capsys.readouterr().out)["aws_calls"] == 0
