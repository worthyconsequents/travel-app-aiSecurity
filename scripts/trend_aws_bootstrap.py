"""Explicit secret synchronization and Kubernetes rendering for the approved AWS lab."""

import argparse
import base64
import json
import os
import subprocess
from pathlib import Path

from scripts.trend_aws import AWS
from scripts.trend_aws_config import TrendAWSConfig
from scripts.trend_aws_manifests import bundle, with_discovery
from scripts.trend_aws_templates import addons

PRIVATE = Path("infra/trend-gateway/private")


def kubectl(c, *args, data=None):
    return subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            str(PRIVATE / "aws-trend-kubeconfig"),
            "--context",
            c.name,
            "-n",
            c.name,
            *args,
        ],
        input=data,
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", opener=lambda n, flags: os.open(n, flags, 0o600)) as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(json.dumps(value, indent=2) + "\n")


def apply_secret(c, name, data):
    # Kubernetes input is passed in memory, never argv, logs, --dry-run output or committed YAML.
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "namespace": c.name},
        "type": "Opaque",
        "data": {k: base64.b64encode(v.encode()).decode() for k, v in data.items()},
    }
    kubectl(
        c,
        "apply",
        "--server-side",
        "--field-manager",
        "boring-travel-deployer",
        "-f",
        "-",
        data=json.dumps(secret),
    )


def owned_secret_exists(client, c, name):
    try:
        details = client.describe_secret(SecretId=name)
    except client.exceptions.ResourceNotFoundException:
        return False
    tags = {x["Key"]: x["Value"] for x in details.get("Tags", [])}
    if tags.get("Deployment") != c.name or tags.get("Project") != "boring-travel":
        raise ValueError("Secret ownership mismatch")
    return True


def secret_tags(c):
    return [
        {"Key": "Project", "Value": "boring-travel"},
        {"Key": "Deployment", "Value": c.name},
        {"Key": "Owner", "Value": "dannytran"},
    ]


def sync(c, profile=None):
    aws = AWS(c, profile)
    outputs = aws.status()["outputs"]
    cluster = aws.client("eks").describe_cluster(name=c.name)["cluster"]
    selected = json.loads(kubectl(c, "config", "view", "--minify", "-o", "json"))
    if selected["clusters"][0]["cluster"]["server"] != cluster["endpoint"]:
        raise ValueError("Kubernetes context does not match the approved AWS cluster")
    client = aws.client("secretsmanager")

    def generated(key):
        return json.loads(
            client.get_secret_value(SecretId=outputs[key + "SecretArn"])["SecretString"]
        )["password"]

    values = {
        "DATABASE_PASSWORD": generated("DatabasePassword"),
        "MCP_SIGNING_KEY": generated("Signing"),
        "MONITOR_PASSWORD": generated("Monitor"),
        "MCP_SERVICE_KEY": generated("Upstream"),
    }
    kubectl(
        c,
        "apply",
        "-f",
        "-",
        data=json.dumps(
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": c.name,
                    "labels": {"pod-security.kubernetes.io/enforce": "restricted"},
                },
            }
        ),
    )
    apply_secret(c, "runtime", values)
    import secrets

    fixture_name = c.name + "-discovery-fixture"
    if owned_secret_exists(client, c, fixture_name):
        fixture = json.loads(client.get_secret_value(SecretId=fixture_name)["SecretString"])
    else:
        fixture = {"control-key": secrets.token_urlsafe(40), "model-key": secrets.token_urlsafe(40)}
        client.create_secret(
            Name=fixture_name, SecretString=json.dumps(fixture), Tags=secret_tags(c)
        )
    apply_secret(c, "discovery-fixture", fixture | {"upstream-key": values["MCP_SERVICE_KEY"]})
    apply_secret(
        c,
        "gateway-upstream-credentials",
        {
            "mcp-boring-travel": values["MCP_SERVICE_KEY"],
            "mock-boring-travel": fixture["model-key"],
            c.name + "-mock": fixture["model-key"],
            **{
                c.name + "-" + suffix: values["MCP_SERVICE_KEY"]
                for suffix in ("discovery", "reservations", "payments", "tool-changes")
            },
        },
    )
    key_file = PRIVATE / "aws-travel-virtual-key"
    secret_name = c.name + "-trend-virtual-key"
    exists = owned_secret_exists(client, c, secret_name)
    key = None
    if key_file.is_symlink():
        raise ValueError("Virtual-key file must not be a symlink")
    if key_file.is_file():
        if key_file.stat().st_mode & 0o077:
            raise ValueError("Virtual-key file requires owner-only permissions")
        key = key_file.read_text().strip()
    elif exists:
        key = client.get_secret_value(SecretId=secret_name)["SecretString"]
    if key is not None:
        if not 20 <= len(key) <= 16000 or any(ch.isspace() for ch in key):
            raise ValueError("Invalid virtual-key file")
        if not exists:
            client.create_secret(Name=secret_name, SecretString=key, Tags=secret_tags(c))
        elif client.get_secret_value(SecretId=secret_name)["SecretString"] != key:
            client.put_secret_value(SecretId=secret_name, SecretString=key)
        apply_secret(c, "trend-virtual-key", {"virtual-key": key})
    key_present = key is not None
    return {
        "runtime_synced": True,
        "virtual_key_synced": key_present,
        "secret_values_displayed": False,
    }


def gateway_values(c):
    return {
        "admin": {"masterKey": {"enabled": True}},
        "podSecurityContext": {
            "runAsNonRoot": True,
            "runAsUser": 1,
            "runAsGroup": 1,
            "fsGroup": 1,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "gateway": {
            "gatewayName": c.name,
            "replicaCount": 1,
            "redis": {"enabled": False},
            "autoscaling": {"enabled": False},
            "ingress": {"enabled": False},
            "service": {"type": "ClusterIP"},
            "secretsDir": {
                "existingSecret": "gateway-upstream-credentials",
                "mountPath": "/etc/secrets/gateway",
            },
            "config": {
                "auth_mode": "vk",
                "mcp_proxy": {"enabled": True},
                "llm_proxy": {"enabled": False},
                "koolaide": {"enabled": True},
            },
            "resources": {
                "requests": {"cpu": "250m", "memory": "1Gi"},
                "limits": {"cpu": "2", "memory": "3Gi"},
            },
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["render-addons", "sync-secrets", "gateway-values", "render-app"]
    )
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--images-file")
    parser.add_argument("--alb-arn")
    parser.add_argument("--profile")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    c = TrendAWSConfig.load(args.env_file)
    directory = Path("build/trend-aws") / c.name
    if args.command == "render-addons":
        save(directory / "addons.json", addons(c))
        result = {"template": str(directory / "addons.json"), "aws_writes": False}
    elif args.command == "gateway-values":
        save(directory / "gateway-values.json", gateway_values(c))
        result = {"values": str(directory / "gateway-values.json"), "aws_writes": False}
    elif args.command == "sync-secrets":
        if not args.apply:
            raise ValueError("Secret synchronization requires explicit --apply")
        result = sync(c, args.profile)
    else:
        if not args.images_file:
            raise ValueError("An immutable image reference file is required")
        aws = AWS(c, args.profile)
        outputs = aws.status()["outputs"]
        if args.alb_arn:
            outputs["AlbArn"] = args.alb_arn
        images = json.loads(Path(args.images_file).read_text())
        value = with_discovery(c, bundle(c, outputs, images), images)
        save(directory / "application.json", value)
        result = {
            "manifest": str(directory / "application.json"),
            "aws_writes": False,
            "requires_alb_binding": not bool(args.alb_arn),
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
