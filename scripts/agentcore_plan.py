"""Render and validate AWS control-plane requests OFFLINE. Never creates a client."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from botocore.session import get_session
from botocore.validate import validate_parameters

ROOT = Path(__file__).resolve().parent.parent


def render(config):
    region, account = config["region"], config["account_id"]
    interceptor = config["interceptor_arn"]
    base = {
        "roleArn": config["gateway_role_arn"],
        "authorizerType": "AWS_IAM",
        "interceptorConfigurations": [
            {
                "interceptor": {"lambda": {"arn": interceptor}},
                "interceptionPoints": ["REQUEST", "RESPONSE"],
                "inputConfiguration": {"passRequestHeaders": False},
            }
        ],
    }
    operations = [
        {"operation": "CreateGateway", "parameters": base | {"name": "boring-travel-inference"}},
        {
            "operation": "CreateGateway",
            "parameters": base
            | {
                "name": "boring-travel-tools",
                "protocolType": "MCP",
                "protocolConfiguration": {"mcp": {"supportedVersions": ["2025-03-26"]}},
            },
        },
        {
            "operation": "CreateGatewayTarget",
            "parameters": {
                "gatewayIdentifier": config["inference_gateway_id"],
                "name": "bedrock-mantle",
                "targetConfiguration": {
                    "inference": {"connector": {"source": {"connectorId": "bedrock-mantle"}}}
                },
                "credentialProviderConfigurations": [
                    {"credentialProviderType": "GATEWAY_IAM_ROLE"}
                ],
            },
        },
    ]
    engine_arn = config["policy_engine_arn"]
    operations[1]["parameters"]["policyEngineConfiguration"] = {
        "arn": engine_arn,
        "mode": "ENFORCE",
    }
    operations.insert(
        0, {"operation": "CreatePolicyEngine", "parameters": {"name": "boring-travel-tools-policy"}}
    )
    for server in ["travel-discovery", "reservations", "customer-payments"]:
        target = config["tool_targets"][server]
        parsed = urlsplit(target["endpoint"])
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Private tool targets require clean HTTPS URLs")
        operations.append(
            {
                "operation": "CreateGatewayTarget",
                "parameters": {
                    "gatewayIdentifier": config["tool_gateway_id"],
                    "name": server,
                    "targetConfiguration": {"mcp": {"mcpServer": {"endpoint": target["endpoint"]}}},
                    "privateEndpoint": {
                        "managedVpcResource": {
                            "vpcIdentifier": config["vpc_id"],
                            "subnetIds": config["private_subnet_ids"],
                            "securityGroupIds": config["security_group_ids"],
                            "endpointIpAddressType": "IPV4",
                        }
                    },
                    "credentialProviderConfigurations": [
                        {
                            "credentialProviderType": "API_KEY",
                            "credentialProvider": {
                                "apiKeyCredentialProvider": {
                                    "providerArn": target["api_key_provider_arn"],
                                    "credentialLocation": "HEADER",
                                    "credentialParameterName": "X-MCP-Service-Key",
                                }
                            },
                        }
                    ],
                },
            }
        )
    gateway_arn = config["tool_gateway_arn"]
    for server, tool in [
        ("travel-discovery", "search_hotels"),
        ("travel-discovery", "get_hotel_details"),
        ("travel-discovery", "search_flights"),
        ("reservations", "get_my_bookings"),
        ("customer-payments", "get_customer_profile"),
    ]:
        statement = (
            f'permit(principal, action == AgentCore::Action::"{server}___{tool}", '
            f'resource == AgentCore::Gateway::"{gateway_arn}");'
        )
        operations.append(
            {
                "operation": "CreatePolicy",
                "parameters": {
                    "policyEngineId": config["policy_engine_id"],
                    "name": "Read-" + tool.replace("_", "-"),
                    "definition": {"policy": {"statement": statement}},
                },
            }
        )
    # Mutations, refunds, bulk records and unknown tools have no permit: default deny.
    model = get_session().get_service_model("bedrock-agentcore-control")
    for operation in operations:
        validate_parameters(
            operation["parameters"], model.operation_model(operation["operation"]).input_shape
        )
    return {
        "cloud_execution": False,
        "region": region,
        "account_id": account,
        "operations": operations,
        "required_before_deploy": [
            "User-approved AWS region, resource inventory, cost estimate and budget",
            "Valid AI Guard API permission/endpoint and an assigned blocking policy",
            "Hosted private TLS MCP targets with X-MCP-Service-Key verification at ingress",
            "AgentCore Identity API-key providers and least-privilege gateway access to them",
            "Gateway caller IAM roles, scoped target/model permissions and Cedar policy in ENFORCE",
            "Private database, server-verified human identity and rotated capability signing keys",
            "Validate provider/Region features and run allow/deny/outage/bypass staging tests",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=ROOT / "infra/agentcore/deployment.example.json"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plan = render(json.loads(args.config.read_text()))
    text = json.dumps(plan, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
