"""Publish a sanitized, content-addressed image set to the new lab's exact ECR repositories."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from cryptography import x509

from scripts.fleet_package import image_context
from scripts.trend_aws import AWS
from scripts.trend_aws_config import TrendAWSConfig


def prepare_context(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Build context destination must be new and empty")
    image_context(Path.cwd(), destination)
    for name in ("Dockerfile.edge", "nginx.conf", "edge.conf.template", "bridge.conf.template"):
        target = destination / "infra/trend-aws" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path("infra/trend-aws") / name, target)
    digest = hashlib.sha256()
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(destination)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def build_secret_args(component, build_ca_file=None):
    if not build_ca_file:
        return []
    if component != "frontend":
        raise ValueError("The optional build CA applies only to the frontend")
    path = Path(build_ca_file).expanduser().resolve(strict=True)
    if not path.is_file() or any(c in str(path) for c in (",", "\n", "\r")):
        raise ValueError("Expected a local certificate file with a plain path")
    data = path.read_bytes()
    if b"PRIVATE KEY" in data:
        raise ValueError("Only public CA certificates may be supplied")
    certificates = x509.load_pem_x509_certificates(data)
    if not certificates or any(
        not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
        for cert in certificates
    ):
        raise ValueError("Expected public PEM CA certificates")
    return ["--secret", "id=corporate_ca,src=" + str(path)]


def publish(c, component, context, tag, profile=None, build_ca_file=None):
    if component not in {"python", "frontend", "edge"}:
        raise ValueError("Unknown image component")
    secret_args = build_secret_args(component, build_ca_file)
    aws = AWS(c, profile)
    aws.identity()
    status = aws.status()
    if status["status"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise ValueError("Foundation must be complete before publishing")
    client = aws.client("ecr")
    repository = c.name + "-" + component
    details = client.describe_repositories(repositoryNames=[repository])["repositories"][0]
    tags = {
        x["Key"]: x["Value"]
        for x in client.list_tags_for_resource(resourceArn=details["repositoryArn"])["tags"]
    }
    if tags.get("Deployment") != c.name or tags.get("Project") != "boring-travel":
        raise ValueError("ECR ownership mismatch")
    registry = details["repositoryUri"].split("/")[0]
    # AWS CLI emits the token only into the login process's stdin, never terminal output.
    args = (
        ["aws"]
        + (["--profile", profile] if profile else [])
        + ["ecr", "get-login-password", "--region", c.region]
    )
    token = subprocess.run(args, check=True, capture_output=True).stdout
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=token,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    dockerfile = {
        "python": "infra/aws-fleet/Dockerfile.python",
        "frontend": "frontend/Dockerfile",
        "edge": "infra/trend-aws/Dockerfile.edge",
    }[component]
    subprocess.run(
        [
            "docker",
            "buildx",
            "build",
            *secret_args,
            "--platform",
            "linux/amd64",
            "--file",
            str(Path(context) / dockerfile),
            "--tag",
            details["repositoryUri"] + ":" + tag,
            "--push",
            str(context),
        ],
        check=True,
    )
    image = client.describe_images(repositoryName=repository, imageIds=[{"imageTag": tag}])[
        "imageDetails"
    ][0]
    return {component: details["repositoryUri"] + "@" + image["imageDigest"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["context", "publish"])
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--component", choices=["python", "frontend", "edge"])
    parser.add_argument("--tag")
    parser.add_argument("--profile")
    parser.add_argument("--build-ca-file", help="Optional public PEM CA for frontend BuildKit only")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    c = TrendAWSConfig.load(args.env_file)
    if args.command == "context":
        print(json.dumps({"context_digest": prepare_context(args.context)}))
    else:
        if not args.apply or not args.component or not args.tag:
            raise ValueError("Publishing requires explicit --apply, --component and --tag")
        print(
            json.dumps(
                publish(c, args.component, args.context, args.tag, args.profile, args.build_ca_file)
            )
        )


if __name__ == "__main__":
    main()
