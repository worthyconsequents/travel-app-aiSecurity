"""Opt-in add-on for an existing AWS Trend app. Plan/render never contact AWS."""

import argparse
import copy
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from botocore.exceptions import ClientError

from scripts.fleet_config import read_env
from scripts.fleet_templates import att, policy, resource, template
from scripts.trend_aws import AWS
from scripts.trend_aws_bootstrap import apply_secret, kubectl, save, secret_tags
from scripts.trend_aws_config import TrendAWSConfig


@dataclass(frozen=True)
class BedrockOption:
    base: TrendAWSConfig
    model_id: str
    enabled: bool
    hourly_requests: int

    @classmethod
    def load(cls, path):
        values = read_env(path)
        base = TrendAWSConfig.load(path)
        mode = values.get("BEDROCK_ENABLE_INFERENCE", "false")
        if mode not in {"true", "false"}:
            raise ValueError("BEDROCK_ENABLE_INFERENCE must be true or false")
        model = values.get("BEDROCK_MODEL_ID", "")
        if model and (
            not re.fullmatch(r"[a-z0-9][a-z0-9.:-]{2,180}", model)
            or model.startswith(("us.", "eu.", "apac.", "global.", "arn:"))
        ):
            raise ValueError("Use an in-region foundation model ID, not a profile or ARN")
        count = values.get("BEDROCK_MAX_REQUESTS_PER_HOUR", "60")
        if not re.fullmatch(r"[0-9]{1,4}", count) or not 1 <= int(count) <= 1000:
            raise ValueError("Hourly model request limit must be between 1 and 1000")
        return cls(base, model, mode == "true", int(count))

    @property
    def model_arn(self):
        if not self.model_id:
            raise ValueError("Set BEDROCK_MODEL_ID to an available in-region tool-use model")
        return f"arn:aws:bedrock:{self.base.region}::foundation-model/{self.model_id}"

    def plan(self):
        return {
            "deployment": self.base.name,
            "model_id": self.model_id or None,
            "model_arn": self.model_arn if self.model_id else None,
            "configuration_complete": bool(self.model_id),
            "aws_writes": False,
            "paid_calls": 0,
            "inference_requested": self.enabled,
            "max_model_calls_per_chat": 4,
            "max_tools_per_chat": 3,
            "max_output_tokens_per_model_call": 400,
            "hourly_request_limit_per_adapter_process": self.hourly_requests,
            "vision_one_console_checkpoint_required": True,
        }


def addon(option):
    c = option.base
    c.validate_provision()
    t = template("Optional boring-travel Bedrock adapter role, key and EKS association.")
    t["Metadata"]["com.aws.cloudformation.Context"] = {
        "ref": [{"at": "docs/bedrock-deployment-option.md", "has": "deployment and activation"}],
        "must": [
            "Only adapter service account invokes one selected model",
            "No streaming, wildcard model access, static AWS keys or inference on creation",
        ],
    }
    tags = secret_tags(c)
    role = resource(
        "IAM::Role",
        {
            "RoleName": c.name + "-bedrock",
            "Tags": tags,
            "AssumeRolePolicyDocument": policy(
                [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "pods.eks.amazonaws.com"},
                        "Action": ["sts:AssumeRole", "sts:TagSession"],
                        "Condition": {
                            "StringEquals": {
                                "aws:SourceAccount": c.account,
                                "aws:RequestTag/eks-cluster-name": c.name,
                                "aws:RequestTag/kubernetes-namespace": c.name,
                                "aws:RequestTag/kubernetes-service-account": "bedrock-adapter",
                            }
                        },
                    }
                ]
            ),
            "Policies": [
                {
                    "PolicyName": "SelectedModelOnly",
                    "PolicyDocument": policy(
                        [
                            {
                                "Effect": "Allow",
                                "Action": ["bedrock:InvokeModel"],
                                "Resource": [option.model_arn],
                            }
                        ]
                    ),
                }
            ],
        },
        "Only the private adapter can invoke the selected in-region model",
        ["No Secrets Manager access; no wildcard model or streaming permissions"],
    )
    t["Resources"] = {
        "AdapterRole": role,
        "ProviderKey": resource(
            "SecretsManager::Secret",
            {
                "Name": c.name + "-bedrock-provider",
                "Tags": tags,
                "GenerateSecretString": {"PasswordLength": 40, "ExcludePunctuation": True},
            },
            "Authenticate Trend to private adapter; unrelated to AWS IAM credentials",
            ["Never print value; retain on stack deletion"],
            DeletionPolicy="Retain",
            UpdateReplacePolicy="Retain",
        ),
        "Association": resource(
            "EKS::PodIdentityAssociation",
            {
                "ClusterName": c.name,
                "Namespace": c.name,
                "ServiceAccount": "bedrock-adapter",
                "RoleArn": att("AdapterRole"),
                "Tags": tags,
            },
            "Temporary workload credentials through the existing EKS Pod Identity agent",
            ["Do not attach role to app, worker, gateway or node service accounts"],
        ),
    }
    t["Outputs"] = {
        "ProviderKeyArn": {"Value": {"Ref": "ProviderKey"}},
        "ModelArn": {"Value": option.model_arn},
    }
    return t


def image_check(c, image):
    if not re.fullmatch(
        rf"{c.account}\.dkr\.ecr\.{c.region}\.amazonaws\.com/"
        rf"{c.name}-python@sha256:[a-f0-9]{{64}}",
        image,
    ):
        raise ValueError("Use the rebuilt Python digest from this deployment's ECR repository")


def manifests(option, image):
    c = option.base
    image_check(c, image)

    def item(kind, name, content, version="v1"):
        return {
            "apiVersion": version,
            "kind": kind,
            "metadata": {"name": name, "namespace": c.name},
            **content,
        }

    env = {
        "APP_MODE": "aws-demo",
        "DEPLOYMENT_PROFILE": "trend-gateway",
        "MODEL_MODE": "bedrock",
        "ENABLE_AWS_BEDROCK": "true",
        "ENABLE_PAID_INFERENCE": "false",
        "AWS_REGION": c.region,
        "BEDROCK_MODEL_ID": option.model_id,
        "TREND_K8S_NAMESPACE": c.name,
        "BEDROCK_PROVIDER_KEY_FILE": "/run/bedrock/provider-key",
        "BEDROCK_MAX_REQUESTS_PER_HOUR": str(option.hourly_requests),
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            item("ServiceAccount", "bedrock-adapter", {"automountServiceAccountToken": False}),
            item(
                "Service",
                "bedrock-adapter",
                {
                    "spec": {
                        "type": "ClusterIP",
                        "selector": {"app": "bedrock-adapter"},
                        "ports": [{"port": 8000, "targetPort": 8000}],
                    }
                },
            ),
            item(
                "Deployment",
                "bedrock-adapter",
                version="apps/v1",
                content={
                    "spec": {
                        "replicas": 1,
                        "strategy": {"type": "Recreate"},
                        "selector": {"matchLabels": {"app": "bedrock-adapter"}},
                        "template": {
                            "metadata": {"labels": {"app": "bedrock-adapter"}},
                            "spec": {
                                "serviceAccountName": "bedrock-adapter",
                                "automountServiceAccountToken": False,
                                "securityContext": {
                                    "runAsNonRoot": True,
                                    "runAsUser": 1000,
                                    "runAsGroup": 1000,
                                    "seccompProfile": {"type": "RuntimeDefault"},
                                },
                                "containers": [
                                    {
                                        "name": "bedrock-adapter",
                                        "image": image,
                                        "command": [
                                            "uvicorn",
                                            "services.bedrock_adapter:create_app",
                                            "--factory",
                                            "--host",
                                            "0.0.0.0",
                                            "--port",
                                            "8000",
                                            "--no-access-log",
                                        ],
                                        "env": [{"name": k, "value": v} for k, v in env.items()],
                                        "ports": [{"containerPort": 8000}],
                                        "securityContext": {
                                            "allowPrivilegeEscalation": False,
                                            "readOnlyRootFilesystem": True,
                                            "capabilities": {"drop": ["ALL"]},
                                        },
                                        "resources": {
                                            "requests": {"cpu": "100m", "memory": "128Mi"},
                                            "limits": {"cpu": "500m", "memory": "256Mi"},
                                        },
                                        "readinessProbe": {
                                            "httpGet": {"path": "/health", "port": 8000}
                                        },
                                        "volumeMounts": [
                                            {
                                                "name": "provider",
                                                "mountPath": "/run/bedrock",
                                                "readOnly": True,
                                            },
                                            {"name": "tmp", "mountPath": "/tmp"},
                                        ],
                                    }
                                ],
                                "volumes": [
                                    {
                                        "name": "provider",
                                        "secret": {
                                            "secretName": "bedrock-provider",
                                            "defaultMode": 0o444,
                                        },
                                    },
                                    {"name": "tmp", "emptyDir": {"sizeLimit": "16Mi"}},
                                ],
                            },
                        },
                    }
                },
            ),
            item(
                "NetworkPolicy",
                "bedrock-adapter",
                {
                    "spec": {
                        "podSelector": {"matchLabels": {"app": "bedrock-adapter"}},
                        "policyTypes": ["Ingress", "Egress"],
                        "ingress": [
                            {
                                "from": [
                                    {
                                        "podSelector": {
                                            "matchLabels": {
                                                "app.kubernetes.io/instance": "trendai-gateway"
                                            }
                                        }
                                    }
                                ],
                                "ports": [{"protocol": "TCP", "port": 8000}],
                            }
                        ],
                        "egress": [
                            {
                                "to": [
                                    {
                                        "namespaceSelector": {
                                            "matchLabels": {
                                                "kubernetes.io/metadata.name": "kube-system"
                                            }
                                        }
                                    }
                                ],
                                "ports": [{"protocol": p, "port": 53} for p in ("TCP", "UDP")],
                            },
                            {
                                "to": [{"ipBlock": {"cidr": "169.254.170.23/32"}}],
                                "ports": [{"protocol": "TCP", "port": 80}],
                            },
                            {
                                "to": [
                                    {
                                        "ipBlock": {
                                            "cidr": "0.0.0.0/0",
                                            "except": [
                                                "10.0.0.0/8",
                                                "172.16.0.0/12",
                                                "192.168.0.0/16",
                                                "169.254.0.0/16",
                                            ],
                                        }
                                    }
                                ],
                                "ports": [{"protocol": "TCP", "port": 443}],
                            },
                        ],
                    }
                },
                "networking.k8s.io/v1",
            ),
        ],
    }


def checklist(option):
    ns = option.base.name
    return f"""# Vision One Bedrock setup for {ns}

Create these dedicated entries; preserve the working mock provider and rule.

| Field | Value |
|---|---|
| Provider name | `{ns}-bedrock` |
| Provider type | OpenAI (the private adapter translates to Bedrock Converse) |
| Base URL | `http://bedrock-adapter.{ns}.svc.cluster.local:8000` (no `/v1`) |
| Credential source | Platform secret file `/etc/secrets/gateway/{ns}-bedrock` |
| Provider model name | `boring-travel-bedrock` (adapter identifier) |
| Actual AWS model ID | `{option.model_id}` (adapter configuration, not provider model field) |
| Alias | `{ns}-bedrock` |
| Exact requested-model match | `{ns}-bedrock-chat` |
| Weight | Bedrock adapter only: 1 / 100%; no mock/local candidates |
| Fallback aliases | Empty |

Enable the exact route. Grant the AWS application identity access to this alias
and the existing reviewed MCP tools. Apply request + response content inspection
to this new model route. Model and MCP access are separate; preserve application
ownership checks. Verify private LLM listener 8080 is enabled. This checklist
is a manual checkpoint, not proof of applied policy, inventory or effective denial.
No tenant API key or AWS credential belongs in the model fields.

After saving, activate through the deploy script with explicit paid-call consent.
Then send one benign chat, correlate token usage/model/tool events, test read-only
behavior and inspect Vision One inventory independently. Do not launch arbitrary
attack/model tests automatically. Existing new-tool ACL finding remains open.
"""


def check_cluster(c, aws):
    aws.identity()
    expected = aws.client("eks").describe_cluster(name=c.name)["cluster"]["endpoint"]
    chosen = json.loads(kubectl(c, "config", "view", "--minify", "-o", "json"))
    if chosen["clusters"][0]["cluster"]["server"] != expected:
        raise ValueError("Kubeconfig points to a different cluster")
    if aws.status()["status"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise ValueError("Existing foundation is not ready")


def provision(option, aws, execute):
    c = option.base
    client = aws.client("cloudformation")
    name = c.name + "-bedrock"
    try:
        stack = client.describe_stacks(StackName=name)["Stacks"][0]
    except ClientError as e:
        # DescribeStacks has no modeled NotFound exception. Restrict expected missing-stack shape.
        if (
            e.response["Error"]["Code"] != "ValidationError"
            or "does not exist" not in e.response["Error"]["Message"]
        ):
            raise
        stack = None
    pending_file = Path("build/trend-aws") / c.name / "bedrock-change-set.json"
    if stack and stack["StackStatus"] == "REVIEW_IN_PROGRESS":
        pending = json.loads(pending_file.read_text())
        if (
            pending["deployment"] != c.name
            or pending["stack_id"] != stack["StackId"]
            or pending["model_arn"] != option.model_arn
        ):
            raise ValueError("Pending change-set ownership/configuration mismatch")
        if not execute:
            return {"change_set_id": pending["change_set_id"], "review_required": True}
        ident = pending["change_set_id"]
        client.get_waiter("change_set_create_complete").wait(
            ChangeSetName=ident, WaiterConfig={"Delay": 5, "MaxAttempts": 36}
        )
        client.execute_change_set(ChangeSetName=ident)
        client.get_waiter("stack_create_complete").wait(
            StackName=name, WaiterConfig={"Delay": 5, "MaxAttempts": 60}
        )
        stack = client.describe_stacks(StackName=name)["Stacks"][0]
    if stack:
        tags = {t["Key"]: t["Value"] for t in stack.get("Tags", [])}
        if tags.get("Deployment") != c.name or tags.get("Project") != "boring-travel":
            raise ValueError("Bedrock stack ownership mismatch")
        if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
            raise ValueError("Inspect existing add-on stack before continuing")
        outputs = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
        if outputs["ModelArn"] != option.model_arn:
            raise ValueError("Model changes require separately reviewed IAM stack update")
        return outputs
    body = json.dumps(addon(option))
    client.validate_template(TemplateBody=body)
    result = client.create_change_set(
        StackName=name,
        ChangeSetName="bedrock-" + secrets.token_hex(6),
        ChangeSetType="CREATE",
        TemplateBody=body,
        Capabilities=["CAPABILITY_NAMED_IAM"],
        Tags=secret_tags(c),
    )
    save(
        pending_file,
        {
            "deployment": c.name,
            "stack_id": result["StackId"],
            "change_set_id": result["Id"],
            "model_arn": option.model_arn,
        },
    )
    if not execute:
        return {"change_set_id": result["Id"], "review_required": True}
    client.get_waiter("change_set_create_complete").wait(
        ChangeSetName=result["Id"], WaiterConfig={"Delay": 5, "MaxAttempts": 36}
    )
    client.execute_change_set(ChangeSetName=result["Id"])
    client.get_waiter("stack_create_complete").wait(
        StackName=name, WaiterConfig={"Delay": 5, "MaxAttempts": 60}
    )
    stack = client.describe_stacks(StackName=name)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}


def template_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prepare(option, image, aws, execute):
    c = option.base
    image_check(c, image)
    check_cluster(c, aws)
    live_api = json.loads(kubectl(c, "get", "deployment", "api", "-o", "json"))
    for container in live_api["spec"]["template"]["spec"]["containers"]:
        if any(
            e.get("name") == "MODEL_MODE" and e.get("value") == "bedrock"
            for e in container.get("env", [])
        ):
            raise ValueError("Roll back active Bedrock chat before preparing another adapter")
    model = aws.client("bedrock").get_foundation_model(modelIdentifier=option.model_id)[
        "modelDetails"
    ]
    if model["modelArn"] != option.model_arn or "ON_DEMAND" not in model["inferenceTypesSupported"]:
        raise ValueError("Selected model is not this in-region on-demand foundation model")
    output = provision(option, aws, execute)
    if output.get("review_required"):
        return output
    client = aws.client("secretsmanager")
    metadata = client.describe_secret(SecretId=output["ProviderKeyArn"])
    tags = {t["Key"]: t["Value"] for t in metadata.get("Tags", [])}
    if tags.get("Deployment") != c.name or tags.get("Project") != "boring-travel":
        raise ValueError("Bedrock provider secret ownership mismatch")
    key = client.get_secret_value(SecretId=output["ProviderKeyArn"])["SecretString"]
    if len(key) < 24:
        raise ValueError("Invalid provider key")
    apply_secret(c, "bedrock-provider", {"provider-key": key})
    # Merge the additional alias in memory; never overwrite existing MCP/mock credentials.
    import base64

    previous = json.loads(kubectl(c, "get", "secret", "gateway-upstream-credentials", "-o", "json"))
    credentials = {k: base64.b64decode(v).decode() for k, v in previous["data"].items()}
    credentials[c.name + "-bedrock"] = key
    apply_secret(c, "gateway-upstream-credentials", credentials)
    # Kubernetes policies are additive: exclude adapter from broad same-namespace ingress/egress.
    same = json.loads(kubectl(c, "get", "networkpolicy", "same-copy", "-o", "json"))
    selector = same["spec"]["podSelector"]
    expression = {"key": "app", "operator": "NotIn", "values": ["bedrock-adapter"]}
    if expression not in selector.get("matchExpressions", []):
        selector.setdefault("matchExpressions", []).append(expression)
    kubectl(
        c,
        "patch",
        "networkpolicy",
        "same-copy",
        "--type=merge",
        "-p",
        json.dumps({"spec": {"podSelector": selector}}),
    )
    kubectl(c, "apply", "-f", "-", data=json.dumps(manifests(option, image)))
    kubectl(c, "rollout", "status", "deployment/bedrock-adapter", "--timeout=120s")
    return {
        "prepared": True,
        "inference_enabled": False,
        "paid_calls": 0,
        "next": "Configure generated Vision One checklist, then explicitly activate",
    }


def activate(option, image, aws, acknowledged):
    if not option.enabled or not acknowledged:
        raise ValueError(
            "Activation requires BEDROCK_ENABLE_INFERENCE=true, model-charge and console acknowledgments"
        )
    c = option.base
    image_check(c, image)
    check_cluster(c, aws)
    api = json.loads(kubectl(c, "get", "deployment", "api", "-o", "json"))
    adapter = json.loads(kubectl(c, "get", "deployment", "bedrock-adapter", "-o", "json"))
    provider = adapter["spec"]["template"]["spec"]["containers"][0]
    configured = {e["name"]: e.get("value") for e in provider.get("env", [])}
    if provider["image"] != image or configured.get("BEDROCK_MODEL_ID") != option.model_id:
        raise ValueError("Prepare the same rebuilt digest and model before activation")
    directory = Path("build/trend-aws") / c.name
    ledger = directory / "bedrock-activation.json"
    if ledger.exists():
        raise ValueError("Activation ledger already exists; inspect or roll back before repeating")
    before = copy.deepcopy(api["spec"]["template"])
    save(ledger, {"deployment": c.name, "before": before, "phase": "activating"})
    # Adapter is activated first. There is no new API route until the second atomic pod patch.
    kubectl(c, "set", "env", "deployment/bedrock-adapter", "ENABLE_PAID_INFERENCE=true")
    kubectl(c, "rollout", "status", "deployment/bedrock-adapter", "--timeout=120s")
    template = copy.deepcopy(before)
    container = template["spec"]["containers"][0]
    container["image"] = image
    values = {
        "MODEL_MODE": "bedrock",
        "ENABLE_AWS_BEDROCK": "true",
        "ENABLE_PAID_INFERENCE": "true",
    }
    container["env"] = [e for e in container.get("env", []) if e["name"] not in values]
    container["env"].extend({"name": k, "value": v} for k, v in values.items())
    kubectl(
        c,
        "patch",
        "deployment",
        "api",
        "--type=merge",
        "-p",
        json.dumps({"spec": {"template": template}}),
    )
    current = json.loads(kubectl(c, "get", "deployment", "api", "-o", "json"))
    save(
        ledger,
        {
            "deployment": c.name,
            "before": before,
            "phase": "patched",
            "active_template_hash": template_hash(current["spec"]["template"]),
        },
    )
    kubectl(c, "rollout", "status", "deployment/api", "--timeout=120s")
    current = json.loads(kubectl(c, "get", "deployment", "api", "-o", "json"))
    save(
        ledger,
        {
            "deployment": c.name,
            "before": before,
            "phase": "active",
            "active_template_hash": template_hash(current["spec"]["template"]),
        },
    )
    return {
        "chat_backend": "bedrock",
        "paid_calls_by_deployer": 0,
        "warning": "Authenticated chat requests can now incur model charges",
    }


def rollback(option, aws):
    c = option.base
    check_cluster(c, aws)
    ledger = Path("build/trend-aws") / c.name / "bedrock-activation.json"
    saved = json.loads(ledger.read_text())
    if saved["deployment"] != c.name:
        raise ValueError("Rollback ledger ownership mismatch")
    # Always close provider before rolling back API, including partially failed activation.
    kubectl(c, "set", "env", "deployment/bedrock-adapter", "ENABLE_PAID_INFERENCE=false")
    kubectl(c, "rollout", "status", "deployment/bedrock-adapter", "--timeout=120s")
    current = json.loads(kubectl(c, "get", "deployment", "api", "-o", "json"))
    if (
        saved.get("phase") in {"active", "patched"}
        and template_hash(current["spec"]["template"]) != saved["active_template_hash"]
    ):
        raise ValueError(
            "Provider disabled; API changed since activation, review rollback manually"
        )
    if saved.get("phase") == "activating" and template_hash(
        current["spec"]["template"]
    ) != template_hash(saved["before"]):
        raise ValueError("Provider disabled; partially changed API requires manual review")
    kubectl(
        c,
        "patch",
        "deployment",
        "api",
        "--type=merge",
        "-p",
        json.dumps({"spec": {"template": saved["before"]}}),
    )
    kubectl(c, "rollout", "status", "deployment/api", "--timeout=120s")
    ledger.rename(ledger.with_name("bedrock-rollback-" + secrets.token_hex(4) + ".json"))
    return {
        "chat_backend": "restored",
        "provider_inference_enabled": False,
        "retained": "Adapter, role and provider secret; no unrelated resource deleted",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["plan", "render", "prepare", "activate", "rollback"])
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--images-file")
    parser.add_argument("--profile")
    for name in (
        "apply",
        "acknowledge-costs",
        "execute-change-set",
        "acknowledge-model-charges",
        "vision-one-configured",
    ):
        parser.add_argument("--" + name, action="store_true")
    args = parser.parse_args()
    option = BedrockOption.load(args.env_file)
    if args.command == "plan":
        result = option.plan()
    else:
        image = ""
        if args.command != "rollback":
            if not args.images_file:
                raise ValueError("Provide --images-file from rebuilt Python publishing")
            image = json.loads(Path(args.images_file).read_text())["python"]
            image_check(option.base, image)
        if args.command == "render":
            directory = Path("build/trend-aws") / option.base.name
            save(directory / "bedrock-addon.json", addon(option))
            save(directory / "bedrock-adapter.json", manifests(option, image))
            target = directory / "bedrock-vision-one-setup.md"
            target.write_text(checklist(option))
            result = {"directory": str(directory), "aws_writes": False, "paid_calls": 0}
        else:
            if not args.apply or not args.acknowledge_costs:
                raise ValueError("Mutation requires --apply --acknowledge-costs")
            aws = AWS(option.base, args.profile)
            if args.command == "prepare":
                result = prepare(option, image, aws, args.execute_change_set)
            elif args.command == "activate":
                result = activate(
                    option,
                    image,
                    aws,
                    args.acknowledge_model_charges and args.vision_one_configured,
                )
            else:
                result = rollback(option, aws)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
