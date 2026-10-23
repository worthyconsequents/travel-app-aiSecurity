"""Strict offline configuration for one isolated boring-travel Trend AWS lab."""

import ipaddress
import re
from dataclasses import asdict, dataclass
from decimal import Decimal

from scripts.fleet_config import read_env


@dataclass(frozen=True)
class TrendAWSConfig:
    name: str
    region: str
    account: str
    hostname: str
    zone: str
    operator_cidr: str
    operator_arn: str
    eks_version: str
    budget: str | None

    @classmethod
    def load(cls, path):
        v = read_env(path)
        if v.get("DEPLOYMENT_PROFILE") != "trend-aws":
            raise ValueError("DEPLOYMENT_PROFILE=trend-aws is required")
        if v.get("ENABLE_PAID_INFERENCE", "false") != "false":
            raise ValueError("This deployment has no paid inference implementation")
        if v.get("DEPLOYMENT_COUNT", "1") != "1":
            raise ValueError("Validate one Trend AWS copy before enabling a fleet")
        prefix = v.get("DEPLOYMENT_PREFIX", "dannytran-boring-travel-trend")
        env = v.get("DEPLOYMENT_ENV", "lab01")
        if not re.fullmatch(r"dannytran-boring-travel(?:-[a-z0-9]+)*", prefix):
            raise ValueError("Use the dannytran-boring-travel naming prefix")
        if not re.fullmatch(r"[a-z][a-z0-9]{0,9}", env):
            raise ValueError("Invalid environment slug")
        name = prefix + "-" + env + "-01"
        if len(name) > 43:
            raise ValueError("Deployment name must leave room for component suffixes")
        region = v.get("AWS_REGION", "us-east-1")
        account = v.get("AWS_EXPECTED_ACCOUNT_ID", "")
        if not re.fullmatch(r"[a-z]{2}-[a-z]+-[0-9]", region):
            raise ValueError("Expected a commercial AWS Region")
        if account and not re.fullmatch(r"[0-9]{12}", account):
            raise ValueError("Invalid expected account")
        hostname = v.get("DEPLOYMENT_HOSTNAME", "")
        if hostname and not re.fullmatch(
            r"boring-travel(?:-[a-z0-9]+)?(?:\.[a-z0-9-]+)+", hostname
        ):
            raise ValueError("Use a boring-travel hostname")
        zone = v.get("DEPLOYMENT_HOSTED_ZONE_ID", "")
        if zone and not re.fullmatch(r"Z[A-Z0-9]+", zone):
            raise ValueError("Invalid hosted zone ID")
        cidr = v.get("DEPLOYMENT_ALLOWED_CIDR", "")
        if cidr:
            network = ipaddress.ip_network(cidr, strict=True)
            if network.version != 4 or network.prefixlen < 24:
                raise ValueError("Operator CIDR must be IPv4 /24 or narrower")
        operator = v.get("AWS_OPERATOR_ARN", "")
        if operator and not re.fullmatch(
            rf"arn:aws:iam::{account}:(user|role)/[A-Za-z0-9+=,.@_/-]+", operator
        ):
            raise ValueError("Provide the IAM user/role ARN, not an STS session ARN")
        version = v.get("AWS_EKS_VERSION", "1.35")
        if not re.fullmatch(r"1\.[0-9]{2}", version):
            raise ValueError("Invalid EKS version")
        budget = v.get("AWS_TEST_BUDGET_USD", "").strip() or None
        if budget is not None and (
            not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", budget) or Decimal(budget) <= 0
        ):
            raise ValueError("Planning budget must be a positive amount or blank")
        return cls(name, region, account, hostname, zone, cidr, operator, version, budget)

    def validate_provision(self):
        if not all((self.account, self.hostname, self.zone, self.operator_cidr, self.operator_arn)):
            raise ValueError(
                "Account, hostname, zone, operator CIDR and IAM principal are required"
            )

    def plan(self):
        return {
            **asdict(self),
            "aws_writes": False,
            "paid_inference": False,
            "deployment_count": 1,
            "gateway_helm_release": "trendai-gateway",
            "resources": {
                "eks_clusters": 1,
                "private_nodes_t3_large": 2,
                "rds_db_t4g_micro_single_az": 1,
                "rds_storage_gb": 20,
                "nat_gateways": 1,
                "public_https_albs": 1,
                "ecr_repositories": 3,
                "cognito_pools": 1,
            },
            "cost_limit_is_not_a_hard_aws_cap": True,
            "cloud_application_acceptance": "NOT_TESTED",
        }
