"""Generic Secrets Manager deployment step. Default is an offline plan.

Authenticate to AWS separately using your normal SDK credential provider.
No login flow, account ID, credentials, or password is embedded in this script.
"""

import argparse
import json
import os
from pathlib import Path


def read_env(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def deploy(env_file, secret_name, region, apply=False, client=None, output=None):
    values = read_env(env_file)
    password = values.get("MONITOR_PASSWORD", "")
    if not 24 <= len(password) <= 256:
        raise ValueError("Set a 24–256 character MONITOR_PASSWORD in the private .env file first")
    plan = {
        "mode": "apply" if apply else "plan",
        "region": region,
        "secret_name": secret_name,
        "operation": "Create a NEW Secrets Manager secret; existing secrets are never overwritten",
        "credential_source": "existing AWS SDK credential chain; authenticate separately",
        "password_source": "MONITOR_PASSWORD in the private env file; never printed",
    }
    if not apply:
        return plan
    if client is None:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "secretsmanager",
            region_name=region,
            config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 1}),
        )
    result = client.create_secret(
        Name=secret_name,
        Description="Private travel application monitoring password",
        SecretString=json.dumps({"password": password}),
    )
    arn = result["ARN"]
    # AWS-generated identifiers must be safe to write as runtime environment values.
    if not arn.startswith("arn:") or ":secretsmanager:" not in arn or any(c.isspace() for c in arn):
        raise RuntimeError("Unexpected Secrets Manager identifier")
    output = output or env_file.parent / "build" / "monitoring"
    output.mkdir(parents=True, exist_ok=True)
    runtime = output / "runtime.env"
    runtime.write_text(
        f"AWS_REGION={region}\nMONITOR_PASSWORD_SOURCE=aws\nMONITOR_SECRET_ARN={arn}\n"
        "ENABLE_AWS_MONITOR_SECRET=true\nMONITOR_COOKIE_SECURE=true\n"
    )
    runtime.chmod(0o600)
    (output / "read-secret-policy.json").write_text(
        json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "secretsmanager:GetSecretValue",
                        "Resource": arn,
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    lines = env_file.read_text().splitlines()
    lines = [line for line in lines if not line.startswith("MONITOR_SECRET_ARN=")]
    lines.append("MONITOR_SECRET_ARN=" + arn)
    env_file.write_text("\n".join(lines) + "\n")
    env_file.chmod(0o600)
    return plan | {
        "secret_arn": arn,
        "runtime_configuration": str(runtime),
        "password_stored": True,
        "aws_resources_deployed": ["one Secrets Manager secret"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--secret-name", default="boring-travel/monitoring")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-west-2"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--apply", action="store_true", help="Create the AWS secret; incurs AWS charges"
    )
    args = parser.parse_args()
    try:
        result = deploy(
            args.env_file, args.secret_name, args.region, args.apply, output=args.output
        )
        print(json.dumps(result, indent=2))
    except Exception as exc:
        # SDK exceptions can carry request details. Print only a class name.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "hint": "Check local configuration and AWS authentication/permissions. "
                    "An existing secret is not overwritten. No secret value was printed.",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
