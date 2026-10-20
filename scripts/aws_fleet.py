"""Isolated AWS demo fleet. plan/render are offline; all AWS writes need explicit flags."""

import argparse
import base64
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from botocore.exceptions import ClientError

from scripts import fleet_templates as templates
from scripts.aws_cloud_test import package
from scripts.fleet_config import FleetConfig

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "boring-travel-fleet"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(value, out, indent=2)
        out.write("\n")
    temporary.replace(path)


def serialize(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def checksum(value):
    return hashlib.sha256(serialize(value).encode()).hexdigest()


class Fleet:
    def __init__(self, config, profile=None, state_root=None, session=None):
        import boto3
        from botocore.config import Config

        self.config = config
        if not config.account:
            raise ValueError("AWS_EXPECTED_ACCOUNT_ID must be set before AWS access")
        self.session = session or boto3.Session(profile_name=profile, region_name=config.region)
        self.sdk_config = Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"total_max_attempts": 3, "mode": "standard"},
            ignore_configured_endpoint_urls=True,
        )
        self.clients = {}
        if self.client("sts").get_caller_identity()["Account"] != config.account:
            raise ValueError("Authenticated AWS account differs from AWS_EXPECTED_ACCOUNT_ID")
        self.directory = (
            (state_root or ROOT / "build/aws-fleet")
            / config.account
            / config.region
            / config.namespace
        )
        self.path = self.directory / "manifest.json"
        self.state = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {
                "schema": 1,
                "account": config.account,
                "region": config.region,
                "namespace": config.namespace,
                "stacks": {},
                "instances": {},
            }
        )
        for field in ("account", "region", "namespace"):
            if self.state.get(field) != getattr(config, field):
                raise ValueError("Manifest scope differs from selected deployment")

    def client(self, name):
        if name not in self.clients:
            self.clients[name] = self.session.client(name, config=self.sdk_config)
        return self.clients[name]

    def persist(self):
        write_json(self.path, self.state)

    @contextmanager
    def lock(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.directory / "operation.lock", os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError(
                    "Another operation is running for this fleet; run serially"
                ) from None
            yield
        finally:
            os.close(fd)

    def owned(self, stack):
        tags = {t["Key"]: t["Value"] for t in stack.get("Tags", [])}
        if tags.get("Project") != PROJECT or tags.get("Namespace") != self.config.namespace:
            raise ValueError("Stack ownership tags differ; refusing to modify it")
        prefix = f"arn:aws:cloudformation:{self.config.region}:{self.config.account}:stack/"
        if not stack["StackId"].startswith(prefix):
            raise ValueError("Stack ARN is outside the selected account/Region")
        return stack

    def lookup(self, name):
        cf = self.client("cloudformation")
        # DescribeStacks has no typed not-found exception; enumerate summaries to
        # distinguish absence without swallowing an unrelated ValidationError.
        active = [
            s
            for page in cf.get_paginator("list_stacks").paginate()
            for s in page["StackSummaries"]
            if s["StackName"] == name and s["StackStatus"] != "DELETE_COMPLETE"
        ]
        if not active:
            return None
        if len(active) != 1:
            raise RuntimeError("Ambiguous stack identity")
        return self.owned(cf.describe_stacks(StackName=active[0]["StackId"])["Stacks"][0])

    def wait(self, stack_id, success):
        # Emit progress so terminal users can distinguish a long RDS wait from a hang.
        for _ in range(360):
            row = self.owned(
                self.client("cloudformation").describe_stacks(StackName=stack_id)["Stacks"][0]
            )
            status = row["StackStatus"]
            if status in success:
                return row
            if status not in {
                "CREATE_IN_PROGRESS",
                "UPDATE_IN_PROGRESS",
                "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
                "DELETE_IN_PROGRESS",
            }:
                raise RuntimeError(
                    f"Stack {row['StackName']} stopped at {status}; inspect its events"
                )
            print(f"{row['StackName']}: {status}", flush=True)
            time.sleep(10)
        raise RuntimeError("Stack operation still running. Resume with the same configuration.")

    def ensure_stack(self, name, body, parameters=None):
        cf = self.client("cloudformation")
        text = serialize(body)
        if len(text.encode()) > 51200:
            raise ValueError("Template exceeds inline limit; split the stack before deploying")
        digest = checksum(body)
        params = [{"ParameterKey": k, "ParameterValue": v} for k, v in (parameters or {}).items()]
        existing = self.lookup(name)
        if existing:
            tags = {t["Key"]: t["Value"] for t in existing["Tags"]}
            if tags.get("Blueprint") != digest:
                raise ValueError(
                    f"{name} has a different blueprint. Use a new DEPLOYMENT_ENV for changed configuration."
                )
            row = self.wait(existing["StackId"], {"CREATE_COMPLETE", "UPDATE_COMPLETE"})
            current_params = {
                p["ParameterKey"]: p["ParameterValue"] for p in row.get("Parameters", [])
            }
            desired_params = {p["ParameterKey"]: p["ParameterValue"] for p in params}
            if desired_params and current_params != desired_params:
                # The only automatic update is binding gateways after private MCP
                # discovery. Template, images, DB and network cannot change here.
                if name not in self.config.instances() or any(current_params.values()):
                    raise ValueError("Refusing to change an already bound deployment")
                cf.update_stack(
                    StackName=row["StackId"],
                    TemplateBody=text,
                    Parameters=params,
                    Capabilities=["CAPABILITY_NAMED_IAM"],
                )
                row = self.wait(row["StackId"], {"UPDATE_COMPLETE"})
        else:
            cf.validate_template(TemplateBody=text)
            result = cf.create_stack(
                StackName=name,
                TemplateBody=text,
                Parameters=params,
                Capabilities=["CAPABILITY_NAMED_IAM"],
                OnFailure="ROLLBACK",
                Tags=[
                    {"Key": "Project", "Value": PROJECT},
                    {"Key": "Namespace", "Value": self.config.namespace},
                    {"Key": "Blueprint", "Value": digest},
                ],
            )
            self.state["stacks"][name] = result["StackId"]
            self.persist()
            row = self.wait(result["StackId"], {"CREATE_COMPLETE"})
        self.state["stacks"][name] = row["StackId"]
        self.persist()
        return {o["OutputKey"]: o["OutputValue"] for o in row.get("Outputs", [])}

    def foundation(self):
        outputs = self.ensure_stack(
            self.config.namespace + "-shared", templates.shared(self.config)
        )
        self.state["foundation"] = outputs
        self.persist()
        return outputs

    def publish_images(self):
        outputs = self.foundation()
        ecr = self.client("ecr")
        credential = ecr.get_authorization_token()["authorizationData"][0]
        username, password = (
            base64.b64decode(credential["authorizationToken"]).decode().split(":", 1)
        )
        subprocess.run(
            [
                "docker",
                "login",
                "--username",
                username,
                "--password-stdin",
                credential["proxyEndpoint"],
            ],
            input=password.encode(),
            check=True,
            stdout=subprocess.DEVNULL,
        )
        # Exact explicit file allowlist prevents .env/vendor files entering Docker contexts.
        from tempfile import TemporaryDirectory

        from scripts.fleet_package import image_context

        with TemporaryDirectory() as temporary:
            context = Path(temporary)
            image_context(ROOT, context)
            for component, dockerfile in (
                ("python", "infra/aws-fleet/Dockerfile.python"),
                ("frontend", "frontend/Dockerfile"),
                ("edge", "infra/aws-fleet/Dockerfile.edge"),
            ):
                # Content identifies the entire sanitized context, including locked dependencies.
                digest = hashlib.sha256()
                for file in sorted(context.rglob("*")):
                    if file.is_file():
                        digest.update(str(file.relative_to(context)).encode())
                        digest.update(file.read_bytes())
                tag = digest.hexdigest()[:24]
                repository = outputs[component.title() + "Repository"]
                repo_name = repository.split("/", 1)[1]
                try:
                    image = ecr.describe_images(
                        repositoryName=repo_name, imageIds=[{"imageTag": tag}]
                    )["imageDetails"][0]
                except ecr.exceptions.ImageNotFoundException:
                    subprocess.run(
                        [
                            "docker",
                            "build",
                            "--platform",
                            "linux/amd64",
                            "-f",
                            str(context / dockerfile),
                            "-t",
                            repository + ":" + tag,
                            str(context),
                        ],
                        check=True,
                    )
                    subprocess.run(["docker", "push", repository + ":" + tag], check=True)
                    image = ecr.describe_images(
                        repositoryName=repo_name, imageIds=[{"imageTag": tag}]
                    )["imageDetails"][0]
                print(
                    "AWS_" + component.upper() + "_IMAGE=" + repository + "@" + image["imageDigest"]
                )

    def preflight(self):
        c = self.config
        c.validate_deploy()
        secret = self.client("secretsmanager").describe_secret(SecretId=c.secret_arn)
        if secret.get("DeletedDate") or not any(
            "AWSCURRENT" in stages for stages in secret.get("VersionIdsToStages", {}).values()
        ):
            raise ValueError("Shared AI Guard secret must have an active AWSCURRENT version")
        actual_key = secret.get("KmsKeyId", "")
        if (
            actual_key
            and actual_key != "alias/aws/secretsmanager"
            and actual_key != c.secret_kms_arn
        ):
            raise ValueError("AI_GUARD_SECRET_KMS_ARN must match the secret's customer-managed key")
        cert = self.client("acm").describe_certificate(CertificateArn=c.certificate)["Certificate"]
        if cert["Status"] != "ISSUED" or "*." + c.domain not in cert.get(
            "SubjectAlternativeNames", []
        ):
            raise ValueError("Provide an ISSUED ACM certificate covering *.DEPLOYMENT_DOMAIN")
        zone = self.client("route53").get_hosted_zone(Id=c.hosted_zone)["HostedZone"]
        zone_name = zone["Name"].rstrip(".")
        if zone["Config"].get("PrivateZone") or not (
            c.domain == zone_name or c.domain.endswith("." + zone_name)
        ):
            raise ValueError("Hosted zone must be public and contain DEPLOYMENT_DOMAIN")
        versions = self.client("rds").describe_db_engine_versions(
            Engine="postgres", EngineVersion="17.11"
        )
        if not versions["DBEngineVersions"]:
            raise ValueError("PostgreSQL 17.11 is unavailable in this Region")
        for image in (c.python_image, c.frontend_image, c.edge_image):
            repository, digest = image.split("/", 1)[1].split("@", 1)
            result = self.client("ecr").batch_get_image(
                repositoryName=repository, imageIds=[{"imageDigest": digest}]
            )
            if result.get("failures") or len(result.get("images", [])) != 1:
                raise ValueError("A configured ECR image digest does not exist")

    def deploy(self):
        self.preflight()
        foundation = self.foundation()
        bucket = foundation["ArtifactBucket"]
        data = package()
        key = "interceptor/" + hashlib.sha256(data).hexdigest() + ".zip"
        s3 = self.client("s3")
        versions = [
            v
            for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=key)
            for v in page.get("Versions", [])
            if v["Key"] == key and v["IsLatest"]
        ]
        if versions:
            version = versions[0]["VersionId"]
        else:
            result = s3.put_object(Bucket=bucket, Key=key, Body=data, ServerSideEncryption="AES256")
            version = result["VersionId"]
        for index, name in enumerate(self.config.instances(), 1):
            base = self.ensure_stack(name, templates.hosting(self.config, index))
            cloud = self.ensure_stack(
                name + "-agentcore",
                templates.agentcore(self.config, index, base, bucket, key, version),
            )
            # HTTP inference URLs must be an origin; MCP uses /mcp.
            cloud["InferenceGatewayUrl"] = cloud["InferenceGatewayUrl"].removesuffix("/mcp")
            self.ensure_stack(name, templates.hosting(self.config, index), cloud)
            self.state["instances"][name] = {
                "hosting": base,
                "gateways": cloud,
                "status": "DEPLOYED_UNTESTED",
            }
            self.persist()
            print(f"{name}: deployment complete, application testing pending. {base['AppUrl']}")

    def status(self):
        # Finds copies beyond the current desired count; never hides/deletes them.
        cf = self.client("cloudformation")
        rows = []
        for page in cf.get_paginator("list_stacks").paginate():
            for summary in page["StackSummaries"]:
                if (
                    not summary["StackName"].startswith(self.config.namespace + "-")
                    or summary["StackStatus"] == "DELETE_COMPLETE"
                ):
                    continue
                row = cf.describe_stacks(StackName=summary["StackId"])["Stacks"][0]
                tags = {t["Key"]: t["Value"] for t in row.get("Tags", [])}
                if (
                    tags.get("Namespace") == self.config.namespace
                    and tags.get("Project") == PROJECT
                ):
                    rows.append(
                        {
                            "name": row["StackName"],
                            "status": row["StackStatus"],
                            "outputs": {
                                o["OutputKey"]: o["OutputValue"] for o in row.get("Outputs", [])
                            },
                        }
                    )
        return {
            "stacks": rows,
            "shared_key": "External secret; never deleted by fleet commands",
            "retained_billable_resources": self.state.get("retained_after_teardown", []),
            "application_test_status": "No live tests performed by status",
        }

    def teardown(self, index, confirmation):
        name = self.config.name(index)
        if confirmation != name:
            raise ValueError("--confirm must exactly match " + name)
        # Preflight BOTH stacks before any deletion, including ownership and names.
        stacks = [self.lookup(n) for n in (name + "-agentcore", name)]
        for row in stacks:
            if row and row["StackName"] not in {name, name + "-agentcore"}:
                raise ValueError("Unexpected stack identity")
        retained = []
        snapshot_databases = []
        cf = self.client("cloudformation")
        for row in stacks:
            if not row:
                continue
            body = cf.get_template(StackName=row["StackId"])["TemplateBody"]
            body = json.loads(body) if isinstance(body, str) else body
            logical = {
                k for k, v in body["Resources"].items() if v.get("DeletionPolicy") == "Retain"
            }
            snapshots = {
                k
                for k, v in body["Resources"].items()
                if v.get("DeletionPolicy") == "Snapshot" and v["Type"] == "AWS::RDS::DBInstance"
            }
            for page in cf.get_paginator("list_stack_resources").paginate(StackName=row["StackId"]):
                retained.extend(
                    {
                        "type": x["ResourceType"],
                        "id": x.get("PhysicalResourceId"),
                        "stack": row["StackName"],
                    }
                    for x in page["StackResourceSummaries"]
                    if x["LogicalResourceId"] in logical
                )
                snapshot_databases.extend(
                    x["PhysicalResourceId"]
                    for x in page["StackResourceSummaries"]
                    if x["LogicalResourceId"] in snapshots and x.get("PhysicalResourceId")
                )
        self.state["retained_after_teardown"] = (
            self.state.get("retained_after_teardown", []) + retained
        )
        self.persist()
        for row in stacks:
            if row:
                cf.delete_stack(StackName=row["StackId"])
                self.wait(row["StackId"], {"DELETE_COMPLETE"})
        for database in snapshot_databases:
            for page in (
                self.client("rds")
                .get_paginator("describe_db_snapshots")
                .paginate(DBInstanceIdentifier=database)
            ):
                retained.extend(
                    {"type": "AWS::RDS::DBSnapshot", "id": s["DBSnapshotIdentifier"]}
                    for s in page["DBSnapshots"]
                )
        self.state["retained_after_teardown"] = self.state.get("retained_after_teardown", []) + [
            x for x in retained if x not in self.state.get("retained_after_teardown", [])
        ]
        self.state["instances"][name] = {"status": "STACKS_DELETED_SNAPSHOT_RETAINED"}
        self.persist()
        return {
            "name": name,
            "retained_billable_resources": retained,
            "shared_foundation": "Preserved",
            "shared_key": "Preserved; externally owned",
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["plan", "render", "foundation", "publish-images", "deploy", "status", "teardown"],
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--profile")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-costs", action="store_true")
    parser.add_argument("--instance", type=int)
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    try:
        config = FleetConfig.load(args.env_file)
        if args.action == "plan":
            print(json.dumps(config.plan(), indent=2))
            return 0
        if args.action == "render":
            config.validate_deploy()
            out = ROOT / "build/aws-fleet/rendered" / config.namespace
            write_json(out / "shared.template.json", templates.shared(config))
            for index in range(1, config.count + 1):
                write_json(
                    out / (config.name(index) + ".template.json"), templates.hosting(config, index)
                )
                write_json(
                    out / (config.name(index) + "-agentcore.template.json"),
                    templates.agentcore(config, index),
                )
            print("All templates rendered offline to " + str(out))
            print(
                "AgentCore parameters represent hosting/artifact outputs; no AWS clients were created."
            )
            return 0
        if args.action != "status" and not (args.apply and args.acknowledge_costs):
            raise ValueError(
                "AWS writes require --apply --acknowledge-costs; plan/render are offline"
            )
        if args.action == "teardown" and (
            args.instance is None or args.confirm != config.name(args.instance)
        ):
            raise ValueError("Teardown needs --instance and --confirm with the exact instance name")
        if args.action == "deploy":
            config.validate_deploy()  # Reject incomplete settings before even creating AWS clients.
        fleet = Fleet(config, args.profile)
        if args.action == "status":
            print(json.dumps(fleet.status(), indent=2))
        else:
            with fleet.lock():
                if args.action == "teardown":
                    print(json.dumps(fleet.teardown(args.instance, args.confirm), indent=2))
                else:
                    getattr(fleet, args.action.replace("-", "_"))()
        return 0
    except ClientError as error:
        print(
            f"AWS {error.response['Error']['Code']} during {error.operation_name}; operation stopped.",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        # SDK / subprocess exception text may include values. Keep logs safe by default.
        if isinstance(error, (ValueError, FileNotFoundError)):
            print(str(error), file=sys.stderr)
        else:
            print(
                f"{type(error).__name__}: operation stopped. Inspect AWS stack events or local build output; resume with the same .env.",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
