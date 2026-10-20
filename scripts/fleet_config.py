"""Offline fleet configuration. Never source .env as executable shell code."""

import ipaddress
import re
from dataclasses import asdict, dataclass
from pathlib import Path


def read_env(path):
    values = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key.strip()):
            raise ValueError(f"Invalid environment assignment on line {number}")
        key, value = key.strip(), value.strip()
        if key in values:
            raise ValueError(f"Duplicate environment setting: {key}")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed quote on line {number}")
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


@dataclass(frozen=True)
class FleetConfig:
    prefix: str
    environment: str
    count: int
    region: str
    account: str
    domain: str
    hosted_zone: str
    certificate: str
    allowed_cidr: str
    secret_arn: str
    secret_kms_arn: str
    ai_guard_url: str
    python_image: str
    frontend_image: str
    edge_image: str
    model_id: str
    model_resource: str
    paid_inference: bool

    @classmethod
    def load(cls, path):
        v = read_env(path)
        if v.get("DEPLOYMENT_TARGET", "aws") != "aws":
            raise ValueError("DEPLOYMENT_TARGET must be aws")
        prefix = v.get("DEPLOYMENT_PREFIX", "dannytran-travel")
        environment = v.get("DEPLOYMENT_ENV", "lab01")
        # Includes component suffixes in the 64-character IAM / Lambda limits.
        if not re.fullmatch(r"dannytran-[a-z0-9]+(?:-[a-z0-9]+)*", prefix):
            raise ValueError("DEPLOYMENT_PREFIX must start dannytran- and use lowercase slugs")
        if not re.fullmatch(r"[a-z][a-z0-9]{0,9}", environment):
            raise ValueError("DEPLOYMENT_ENV must be a 1–10 character lowercase alphanumeric slug")
        if len(f"{prefix}-{environment}") > 35:
            raise ValueError("Combined prefix and environment exceed 35 characters")
        raw_count = v.get("DEPLOYMENT_COUNT", "1")
        if not re.fullmatch(r"[1-9][0-9]?", raw_count):
            raise ValueError("DEPLOYMENT_COUNT must be an integer from 1 to 20")
        count = int(raw_count)
        if count > 20:
            raise ValueError("DEPLOYMENT_COUNT must be from 1 to 20")
        region = v.get("AWS_REGION", "us-east-1")
        if not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", region):
            raise ValueError("Use a commercial AWS Region")
        account = v.get("AWS_EXPECTED_ACCOUNT_ID", "")
        if account and not re.fullmatch(r"\d{12}", account):
            raise ValueError("AWS_EXPECTED_ACCOUNT_ID must have 12 digits")
        domain = v.get("DEPLOYMENT_DOMAIN", "").rstrip(".")
        if domain and not re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}", domain
        ):
            raise ValueError("DEPLOYMENT_DOMAIN must be a DNS domain")
        cidr = v.get("DEPLOYMENT_ALLOWED_CIDR", "")
        if cidr:
            network = ipaddress.ip_network(cidr, strict=True)
            if network.version != 4 or network.prefixlen < 24:
                raise ValueError("Provide an operator IPv4 CIDR of /24 or narrower")
        paid = v.get("ENABLE_PAID_INFERENCE", "false")
        if paid not in {"true", "false"}:
            raise ValueError("ENABLE_PAID_INFERENCE must be true or false")
        from services.agentcore.inspection import AIGuardInspector

        url = v.get(
            "AI_GUARD_URL", "https://api.xdr.trendmicro.com/v3.0/aiSecurity/applyGuardrails"
        )
        AIGuardInspector(url, "offline-validation", prefix)
        config = cls(
            prefix,
            environment,
            count,
            region,
            account,
            domain,
            v.get("DEPLOYMENT_HOSTED_ZONE_ID", ""),
            v.get("DEPLOYMENT_CERTIFICATE_ARN", ""),
            cidr,
            v.get("AI_GUARD_SECRET_ARN", ""),
            v.get("AI_GUARD_SECRET_KMS_ARN", ""),
            url,
            v.get("AWS_PYTHON_IMAGE", ""),
            v.get("AWS_FRONTEND_IMAGE", ""),
            v.get("AWS_EDGE_IMAGE", ""),
            v.get("AGENTCORE_MODEL_ID", ""),
            v.get("AGENTCORE_MANTLE_PROJECT_ARN", ""),
            paid == "true",
        )
        return config

    @property
    def namespace(self):
        return f"{self.prefix}-{self.environment}"

    def name(self, index):
        if not 1 <= index <= 20:
            raise ValueError("Instance index must be 1–20")
        return f"{self.namespace}-{index:02d}"

    def instances(self):
        return [self.name(i) for i in range(1, self.count + 1)]

    def validate_deploy(self):
        required = {
            "AWS_EXPECTED_ACCOUNT_ID": self.account,
            "DEPLOYMENT_DOMAIN": self.domain,
            "DEPLOYMENT_HOSTED_ZONE_ID": self.hosted_zone,
            "DEPLOYMENT_CERTIFICATE_ARN": self.certificate,
            "DEPLOYMENT_ALLOWED_CIDR": self.allowed_cidr,
            "AI_GUARD_SECRET_ARN": self.secret_arn,
            "AWS_PYTHON_IMAGE": self.python_image,
            "AWS_FRONTEND_IMAGE": self.frontend_image,
            "AWS_EDGE_IMAGE": self.edge_image,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError("Required before deployment: " + ", ".join(missing))
        arn_base = f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:"
        if not self.secret_arn.startswith(arn_base) or "*" in self.secret_arn:
            raise ValueError("Shared secret must be an exact ARN in the chosen account and Region")
        if not self.certificate.startswith(
            f"arn:aws:acm:{self.region}:{self.account}:certificate/"
        ):
            raise ValueError("Certificate must belong to the chosen account and Region")
        if self.secret_kms_arn and not re.fullmatch(
            rf"arn:aws:kms:{self.region}:{self.account}:key/[a-zA-Z0-9-]+", self.secret_kms_arn
        ):
            raise ValueError(
                "Custom secret KMS key must be an exact key ARN in this account/Region"
            )
        for image in (self.python_image, self.frontend_image, self.edge_image):
            if not re.fullmatch(
                rf"{self.account}\.dkr\.ecr\.{self.region}\.amazonaws\.com/"
                r"[a-z0-9/_-]+@sha256:[0-9a-f]{64}",
                image,
            ):
                raise ValueError(
                    "Images must be immutable ECR digest references in this account/Region"
                )
        if self.paid_inference and (
            not re.fullmatch(r"bedrock-mantle/[A-Za-z0-9._-]+", self.model_id)
            or self.model_resource
            != f"arn:aws:bedrock-mantle:{self.region}:{self.account}:project/default"
        ):
            raise ValueError(
                "Paid inference requires a bedrock-mantle/model ID and exact default Mantle project ARN"
            )

    def plan(self):
        return {
            "cloud_execution": False,
            "namespace": self.namespace,
            "shared_stack": self.namespace + "-shared",
            "region": self.region,
            "expected_account": self.account or "UNSET",
            "shared_ai_guard_secret_arn": self.secret_arn or "UNSET",
            "paid_inference": self.paid_inference,
            "instances": [
                {
                    "name": name,
                    "hosting_stack": name,
                    "agentcore_stack": name + "-agentcore",
                    "url": f"https://{name}.{self.domain or 'YOUR-DOMAIN'}",
                    "monitor_url": f"https://{name}.{self.domain or 'YOUR-DOMAIN'}/monitor",
                    "monitor_secret_name": name + "-monitor",
                    "vpc_cidr": f"10.{80 + index}.0.0/16",
                }
                for index, name in enumerate(self.instances(), 1)
            ],
            "costs": "Each copy adds Fargate, RDS, two ALBs, NAT, logs, secrets and Lattice. "
            "Count is not a spending cap. Paid model calls default to disabled.",
            "lifecycle": "Count increases add copies; decreases never delete. Teardown selects one copy. "
            "Shared key is external and is never deleted by these scripts.",
        }

    def snapshot(self):
        """All fields are configuration references, never credential values."""
        return asdict(self)
