"""One-copy Trend AWS preparation and guarded foundation creation. Never logs secrets."""

import argparse
import json
from pathlib import Path

from scripts.trend_aws_config import TrendAWSConfig
from scripts.trend_aws_templates import foundation


class AWS:
    def __init__(self, config, profile=None):
        import boto3
        from botocore.config import Config

        self.config = config
        self.session = boto3.Session(profile_name=profile, region_name=config.region)
        self.clients = {}
        self.options = Config(
            connect_timeout=5,
            read_timeout=15,
            retries={"mode": "standard", "total_max_attempts": 2},
        )

    def client(self, service):
        if service not in self.clients:
            self.clients[service] = self.session.client(service, config=self.options)
        return self.clients[service]

    def identity(self):
        result = self.client("sts").get_caller_identity()
        if result["Account"] != self.config.account:
            raise ValueError("AWS account does not match the explicit deployment account")
        return result

    def preflight(self):
        c = self.config
        c.validate_provision()
        self.identity()
        route53 = self.client("route53")
        zone = route53.get_hosted_zone(Id=c.zone)["HostedZone"]
        if zone["Config"].get("PrivateZone") or not c.hostname.endswith(
            "." + zone["Name"].rstrip(".")
        ):
            raise ValueError("Approved hostname must be within the specified public hosted zone")
        records = route53.list_resource_record_sets(
            HostedZoneId=c.zone, StartRecordName=c.hostname + ".", MaxItems="1"
        )["ResourceRecordSets"]
        if any(r["Name"] == c.hostname + "." for r in records):
            raise ValueError(
                "Hostname is already in use; never overwrite another application's DNS"
            )
        versions = self.client("eks").describe_cluster_versions(clusterVersions=[c.eks_version])[
            "clusterVersions"
        ]
        if not any(
            v["clusterVersion"] == c.eks_version and v["status"] == "STANDARD_SUPPORT"
            for v in versions
        ):
            raise ValueError("Choose a verified EKS version in standard support")
        engines = self.client("rds").describe_db_engine_versions(
            Engine="postgres", EngineVersion="17.11"
        )["DBEngineVersions"]
        if not any(v["Status"] == "available" for v in engines):
            raise ValueError("RDS PostgreSQL 17.11 is unavailable")
        stacks = self.client("cloudformation").get_paginator("list_stacks").paginate()
        owned = [
            s
            for page in stacks
            for s in page["StackSummaries"]
            if s["StackName"] == c.name + "-foundation" and s["StackStatus"] != "DELETE_COMPLETE"
        ]
        if owned:
            raise ValueError(
                "Foundation stack already exists; inspect its status instead of overwriting"
            )
        return {
            "account_verified": True,
            "region": c.region,
            "hostname_unused": True,
            "eks_standard_support": True,
            "postgres_available": True,
            "aws_writes": False,
        }

    def create(self):
        self.preflight()
        c = self.config
        body = json.dumps(foundation(c), separators=(",", ":"))
        if len(body.encode()) > 51200:
            raise ValueError("Foundation exceeds inline template limit; split it before deployment")
        response = self.client("cloudformation").create_stack(
            StackName=c.name + "-foundation",
            TemplateBody=body,
            Capabilities=["CAPABILITY_NAMED_IAM"],
            OnFailure="ROLLBACK",
            ClientRequestToken=c.name + "-initial",
            Tags=[
                {"Key": "Project", "Value": "boring-travel"},
                {"Key": "Owner", "Value": "dannytran"},
                {"Key": "Deployment", "Value": c.name},
            ],
        )
        return {
            "stack_id": response["StackId"],
            "status": "CREATION_REQUESTED_NOT_ACCEPTANCE_TESTED",
        }

    def status(self):
        self.identity()
        stack = self.client("cloudformation").describe_stacks(
            StackName=self.config.name + "-foundation"
        )["Stacks"][0]
        tags = {t["Key"]: t["Value"] for t in stack.get("Tags", [])}
        if tags.get("Project") != "boring-travel" or tags.get("Deployment") != self.config.name:
            raise ValueError("Stack ownership mismatch")
        return {
            "status": stack["StackStatus"],
            "outputs": {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])},
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["plan", "render", "preflight", "create-foundation", "status"]
    )
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-costs", action="store_true")
    args = parser.parse_args()
    c = TrendAWSConfig.load(args.env_file)
    if args.command == "plan":
        result = c.plan()
    elif args.command == "render":
        directory = Path("build/trend-aws") / c.name
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / "foundation.json"
        destination.write_text(json.dumps(foundation(c), indent=2) + "\n")
        result = {"template": str(destination), "aws_writes": False}
    else:
        if args.command == "create-foundation" and not (args.apply and args.acknowledge_costs):
            raise ValueError(
                "Foundation creation requires explicit --apply and --acknowledge-costs"
            )
        aws = AWS(c, args.profile)
        result = (
            aws.create() if args.command == "create-foundation" else getattr(aws, args.command)()
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
