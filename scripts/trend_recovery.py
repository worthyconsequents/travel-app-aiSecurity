"""Encrypted recovery capture for the exact AWS Trend deployment; never tears it down."""

import argparse
import base64
import hashlib
import io
import json
import os
import secrets
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scripts.fleet_templates import compact
from scripts.trend_aws import AWS
from scripts.trend_aws_bootstrap import PRIVATE, kubectl, save, secret_tags
from scripts.trend_aws_config import TrendAWSConfig

MAGIC = b"BORING-RECOVERY-1\n"
MAX_SIZE = 128 * 1024 * 1024


def encode(value):
    return (json.dumps(value, indent=2, default=str) + "\n").encode()


def private_write(path, data):
    path = Path(path)
    with open(path, "xb", opener=lambda n, flags: os.open(n, flags, 0o600)) as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(data)


def safe_path(name):
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts or "\\" in name:
        raise ValueError("Unsafe recovery archive member")
    return p


def encrypt_files(files, key, deployment):
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    files = dict(files) | {"CHECKSUMS.json": encode(hashes)}
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        for name, data in sorted(files.items()):
            safe_path(name)
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(data), 0o600
            tar.addfile(entry, io.BytesIO(data))
    plain = stream.getvalue()
    if len(plain) > MAX_SIZE:
        raise ValueError("Recovery bundle exceeds bounded archive size")
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, plain, deployment.encode())


def decrypt_files(blob, key, deployment):
    if not blob.startswith(MAGIC) or len(blob) > MAX_SIZE + 100:
        raise ValueError("Unsupported recovery archive")
    offset = len(MAGIC)
    plain = AESGCM(key).decrypt(
        blob[offset : offset + 12], blob[offset + 12 :], deployment.encode()
    )
    result, size = {}, 0
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tar:
        for entry in tar:
            safe_path(entry.name)
            size += entry.size
            if not entry.isfile() or size > MAX_SIZE or entry.name in result:
                raise ValueError("Invalid recovery archive contents")
            with tar.extractfile(entry) as f:
                result[entry.name] = f.read()
    expected = json.loads(result.pop("CHECKSUMS.json"))
    actual = {name: hashlib.sha256(data).hexdigest() for name, data in result.items()}
    if expected != actual:
        raise ValueError("Recovery contents checksum mismatch")
    return result


def clean_object(value):
    value = json.loads(json.dumps(value))
    value.pop("status", None)
    metadata = value.get("metadata", {})
    for key in (
        "uid",
        "resourceVersion",
        "generation",
        "creationTimestamp",
        "managedFields",
        "selfLink",
        "ownerReferences",
        "finalizers",
    ):
        metadata.pop(key, None)
    metadata.get("annotations", {}).pop("kubectl.kubernetes.io/last-applied-configuration", None)
    if value.get("kind") == "Service":
        for key in ("clusterIP", "clusterIPs", "healthCheckNodePort", "loadBalancerIP"):
            value.get("spec", {}).pop(key, None)
    if value.get("kind") == "ServiceAccount":
        value.pop("secrets", None)
    return value


def ensure_bucket(c, s3):
    name = compact(c.name, "recovery") + "-" + c.account
    exists = True
    try:
        s3.head_bucket(Bucket=name, ExpectedBucketOwner=c.account)
    except ClientError as error:
        if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
            raise
        exists = False
    if exists:
        tags = {
            t["Key"]: t["Value"]
            for t in s3.get_bucket_tagging(Bucket=name, ExpectedBucketOwner=c.account)["TagSet"]
        }
        if tags.get("Deployment") != c.name or tags.get("Project") != "boring-travel":
            raise ValueError("Recovery bucket ownership mismatch")
        block = s3.get_public_access_block(Bucket=name, ExpectedBucketOwner=c.account)[
            "PublicAccessBlockConfiguration"
        ]
        if not all(
            block.get(k)
            for k in (
                "BlockPublicAcls",
                "IgnorePublicAcls",
                "BlockPublicPolicy",
                "RestrictPublicBuckets",
            )
        ):
            raise ValueError("Existing recovery bucket public-access controls changed")
        if (
            s3.get_bucket_versioning(Bucket=name, ExpectedBucketOwner=c.account).get("Status")
            != "Enabled"
        ):
            raise ValueError("Existing recovery bucket versioning changed")
    else:
        args = {"Bucket": name}
        if c.region != "us-east-1":
            args["CreateBucketConfiguration"] = {"LocationConstraint": c.region}
        s3.create_bucket(**args)
        s3.put_public_access_block(
            Bucket=name,
            PublicAccessBlockConfiguration={
                k: True
                for k in (
                    "BlockPublicAcls",
                    "IgnorePublicAcls",
                    "BlockPublicPolicy",
                    "RestrictPublicBuckets",
                )
            },
        )
        s3.put_bucket_ownership_controls(
            Bucket=name, OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
        )
        s3.put_bucket_encryption(
            Bucket=name,
            ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            },
        )
        s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
        s3.put_bucket_tagging(
            Bucket=name,
            Tagging={
                "TagSet": secret_tags(c) + [{"Key": "Purpose", "Value": "recovery-before-teardown"}]
            },
        )
        s3.put_bucket_policy(
            Bucket=name,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "RequireTLS",
                            "Effect": "Deny",
                            "Principal": "*",
                            "Action": "s3:*",
                            "Resource": [f"arn:aws:s3:::{name}", f"arn:aws:s3:::{name}/*"],
                            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                        }
                    ],
                }
            ),
        )
    return name


def capture(c, env_file, snapshot_id, profile=None):
    aws = AWS(c, profile)
    aws.identity()
    status = aws.status()
    endpoint = aws.client("eks").describe_cluster(name=c.name)["cluster"]
    selected = json.loads(kubectl(c, "config", "view", "--minify", "-o", "json"))
    if selected["clusters"][0]["cluster"]["server"] != endpoint["endpoint"]:
        raise ValueError("Kubernetes context is not this deployment")
    rds = aws.client("rds")
    snapshot = rds.describe_db_snapshots(DBSnapshotIdentifier=snapshot_id)["DBSnapshots"][0]
    tags = {
        t["Key"]: t["Value"]
        for t in rds.list_tags_for_resource(ResourceName=snapshot["DBSnapshotArn"])["TagList"]
    }
    if (
        snapshot["DBInstanceIdentifier"] != c.name + "-db"
        or snapshot["Status"] != "available"
        or not snapshot.get("Encrypted")
        or tags.get("Deployment") != c.name
        or tags.get("Project") != "boring-travel"
    ):
        raise ValueError("Snapshot must be available, encrypted and owned by this deployment")
    kms = aws.client("kms").describe_key(KeyId=snapshot["KmsKeyId"])["KeyMetadata"]
    if kms["KeyState"] != "Enabled":
        raise ValueError("Snapshot encryption key is not enabled")
    now = datetime.now(timezone.utc)
    ident = now.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    directory = PRIVATE / "recovery" / ident
    directory.mkdir(parents=True, mode=0o700)
    os.chmod(directory.parent, 0o700)
    os.chmod(directory, 0o700)
    files = {}

    def add(name, value):
        files[name] = value if isinstance(value, bytes) else encode(value)

    add(
        "manifest.json",
        {
            "format": 1,
            "deployment": c.name,
            "region": c.region,
            "account": c.account,
            "captured_at": now.isoformat(),
            "snapshot": snapshot,
            "snapshot_key": {k: kms[k] for k in ("Arn", "KeyManager", "KeyState")},
            "foundation": status,
            "database_data_in_archive": False,
            "restore_tested": False,
            "external_dependencies": [
                "retained RDS snapshot and KMS key in original account",
                "retained ECR digests",
                "AWS access",
                "new Trend enrollment may be required",
                "Cognito password reset/reinvitation if pool recreated",
            ],
        },
    )
    add("private/deployment.env", Path(env_file).read_bytes())
    add("aws/cluster.json", endpoint)
    cf = aws.client("cloudformation")
    for suffix in ("foundation", "addons"):
        name = c.name + "-" + suffix
        stack = cf.describe_stacks(StackName=name)["Stacks"][0]
        tags = {t["Key"]: t["Value"] for t in stack.get("Tags", [])}
        if tags.get("Project") != "boring-travel" or tags.get("Deployment") != c.name:
            raise ValueError("Stack ownership mismatch")
        add("aws/" + suffix + "-stack.json", stack)
        body = cf.get_template(StackName=name, TemplateStage="Original")["TemplateBody"]
        add("aws/" + suffix + "-template.json", json.loads(body) if isinstance(body, str) else body)
        resources = [
            x
            for page in cf.get_paginator("list_stack_resources").paginate(StackName=name)
            for x in page["StackResourceSummaries"]
        ]
        add("aws/" + suffix + "-resources.json", resources)
    resources = "deployments,statefulsets,daemonsets,services,configmaps,secrets,serviceaccounts,networkpolicies,ingresses,limitranges,resourcequotas,cronjobs,persistentvolumeclaims,roles,rolebindings,poddisruptionbudgets"
    captured = json.loads(kubectl(c, "get", resources, "-o", "json"))
    add("kubernetes/captured.json", captured)
    add(
        "kubernetes/review-before-apply.json",
        {
            "apiVersion": "v1",
            "kind": "List",
            "items": [
                clean_object(x)
                for x in captured["items"]
                if x.get("type") != "kubernetes.io/service-account-token"
            ],
        },
    )
    add(
        "kubernetes/gateway-coordination-reference.json",
        json.loads(kubectl(c, "get", "leases", "-o", "json")),
    )
    helm = PRIVATE / "helm"

    def helm_call(*args):
        return subprocess.run(
            [
                str(helm),
                "--kubeconfig",
                str(PRIVATE / "aws-trend-kubeconfig"),
                "--kube-context",
                c.name,
                *args,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.encode()

    add(
        "helm/trend-values.json",
        helm_call("get", "values", "trendai-gateway", "-n", c.name, "--all", "-o", "json"),
    )
    add("helm/trend-manifest.yaml", helm_call("get", "manifest", "trendai-gateway", "-n", c.name))
    add("helm/releases.json", helm_call("list", "--all-namespaces", "-o", "json"))
    secrets_client = aws.client("secretsmanager")
    saved_secrets = []
    for page in secrets_client.get_paginator("list_secrets").paginate(
        Filters=[{"Key": "name", "Values": [c.name + "-"]}]
    ):
        for secret in page["SecretList"]:
            tags = {t["Key"]: t["Value"] for t in secret.get("Tags", [])}
            if tags.get("Project") == "boring-travel" and tags.get("Deployment") == c.name:
                saved_secrets.append(
                    {
                        "metadata": secret,
                        "value": secrets_client.get_secret_value(SecretId=secret["ARN"]),
                    }
                )
    add("private/secrets-manager.json", saved_secrets)
    pool = status["outputs"]["OperatorPoolId"]
    cog = aws.client("cognito-idp")
    add("aws/cognito-pool.json", cog.describe_user_pool(UserPoolId=pool))
    add(
        "private/cognito-client.json",
        cog.describe_user_pool_client(
            UserPoolId=pool, ClientId=status["outputs"]["OperatorClientId"]
        ),
    )
    add(
        "private/cognito-users.json",
        [
            u
            for page in cog.get_paginator("list_users").paginate(UserPoolId=pool)
            for u in page["Users"]
        ],
    )
    zone = aws.client("route53").get_hosted_zone(Id=c.zone)
    add("aws/dns-zone.json", zone)
    add(
        "aws/dns-record.json",
        [
            x
            for page in aws.client("route53")
            .get_paginator("list_resource_record_sets")
            .paginate(HostedZoneId=c.zone)
            for x in page["ResourceRecordSets"]
            if x["Name"].rstrip(".") == c.hostname
        ],
    )
    images = []
    for component in ("python", "frontend", "edge"):
        repo = c.name + "-" + component
        meta = aws.client("ecr").describe_repositories(repositoryNames=[repo])["repositories"][0]
        repo_tags = {
            t["Key"]: t["Value"]
            for t in aws.client("ecr").list_tags_for_resource(resourceArn=meta["repositoryArn"])[
                "tags"
            ]
        }
        if repo_tags.get("Deployment") != c.name or repo_tags.get("Project") != "boring-travel":
            raise ValueError("ECR ownership mismatch")
        images.append(
            {
                "repository": meta,
                "images": [
                    x
                    for page in aws.client("ecr")
                    .get_paginator("describe_images")
                    .paginate(repositoryName=repo)
                    for x in page["imageDetails"]
                ],
            }
        )
    add("aws/retained-ecr-images.json", images)
    root = Path.cwd()
    names = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    for name in names:
        if not name or any(
            p in PurePosixPath(name).parts
            for p in ("private", ".git", "AI_Gateway", "AI-gateway", "build")
        ):
            continue
        p = root / name
        if p.is_file() and not p.is_symlink():
            add("source/" + name, p.read_bytes())
    # Capture the new recovery tool/runbook even before their later Git publication.
    for name in (
        "scripts/trend_recovery.py",
        "docs/recovery-bundle.md",
        "tests/unit/test_recovery.py",
    ):
        if Path(name).is_file():
            add("source/" + name, Path(name).read_bytes())
    with tempfile.TemporaryDirectory(prefix="git-capture-", dir=directory) as tmp:
        git = Path(tmp) / "repository.bundle"
        subprocess.run(
            ["git", "bundle", "create", str(git), "--all"], check=True, capture_output=True
        )
        os.chmod(git, 0o600)
        subprocess.run(["git", "bundle", "verify", str(git)], check=True, capture_output=True)
        add("source/repository.bundle", git.read_bytes())
    add(
        "source/git-state.json",
        {
            "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "branch": subprocess.check_output(
                ["git", "branch", "--show-current"], text=True
            ).strip(),
            "status": subprocess.check_output(["git", "status", "--porcelain"], text=True),
        },
    )
    for filename in (
        "images.json",
        "recovery-storage-inventory.json",
        "recovery-cost-estimate.json",
    ):
        p = Path("build/trend-aws") / c.name / filename
        if p.exists():
            add("ledgers/" + filename, p.read_bytes())
    key = AESGCM.generate_key(bit_length=256)
    archive = encrypt_files(files, key, c.name)
    if decrypt_files(archive, key, c.name) != files:
        raise ValueError("Local archive verification failed")
    local = directory / "recovery.btar.aesgcm"
    key_path = directory / "bundle-key"
    private_write(local, archive)
    private_write(key_path, base64.b64encode(key) + b"\n")
    # Local-only capture: re-read the persisted ciphertext and verify every file.
    digest = hashlib.sha256(archive).digest()
    restored = local.read_bytes()
    if hashlib.sha256(restored).digest() != digest or decrypt_files(restored, key, c.name) != files:
        raise ValueError("Persisted local recovery verification failed")
    receipt = {
        "deployment": c.name,
        "region": c.region,
        "account": c.account,
        "captured_at": now.isoformat(),
        "snapshot_id": snapshot_id,
        "snapshot_arn": snapshot["DBSnapshotArn"],
        "snapshot_status": snapshot["Status"],
        "snapshot_encrypted": True,
        "storage_destination": "local-only",
        "sha256": digest.hex(),
        "archive_bytes": len(archive),
        "file_count": len(files),
        "local_archive": str(local.resolve()),
        "key_file": str(key_path.resolve()),
        "local_integrity_verified": True,
        "remote_integrity_verified": False,
        "database_restore_tested": False,
        "teardown_performed": False,
        "retained_dependencies": ["snapshot", "KMS key", "ECR images"],
        "key_warning": "Store this key separately off this computer. Never upload it with archive or commit it.",
    }
    save(directory / "receipt.json", receipt)
    save(Path("build/trend-aws") / c.name / "latest-recovery-receipt.json", receipt)
    return {
        "receipt_file": str((directory / "receipt.json").resolve()),
        "snapshot_status": "available",
        "archive_bytes": len(archive),
        "files": len(files),
        "remote_verified": False,
        "local_verified": True,
        "teardown_performed": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["capture", "verify", "unpack"])
    p.add_argument("--env-file")
    p.add_argument("--deployment")
    p.add_argument("--snapshot-id")
    p.add_argument("--archive")
    p.add_argument("--key-file")
    p.add_argument("--output")
    p.add_argument("--profile")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--acknowledge-costs", action="store_true")
    args = p.parse_args()
    if args.command == "capture":
        if not args.env_file:
            raise ValueError("Capture requires --env-file")
        c = TrendAWSConfig.load(args.env_file)
        if not args.apply or not args.acknowledge_costs or not args.snapshot_id:
            raise ValueError("Capture requires owned snapshot, --apply and --acknowledge-costs")
        result = capture(c, args.env_file, args.snapshot_id, args.profile)
    else:
        deployment = args.deployment or (
            TrendAWSConfig.load(args.env_file).name if args.env_file else ""
        )
        if not deployment:
            raise ValueError("Verify/unpack requires --deployment or --env-file")
        key_file = Path(args.key_file)
        if key_file.stat().st_mode & 0o077:
            raise ValueError("Recovery key requires owner-only permissions")
        files = decrypt_files(
            Path(args.archive).read_bytes(), base64.b64decode(key_file.read_bytes()), deployment
        )
        if args.command == "unpack":
            output = Path(args.output)
            output.mkdir(mode=0o700, parents=True, exist_ok=False)
            for name, data in files.items():
                target = output / safe_path(name)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                private_write(target, data)
        result = {"integrity_verified": True, "files": len(files), "aws_calls": 0}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
