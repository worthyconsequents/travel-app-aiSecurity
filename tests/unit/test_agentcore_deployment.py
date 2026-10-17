import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def test_cloud_plan_is_generated_without_aws_clients():
    spec = importlib.util.spec_from_file_location(
        "agentcore_plan", ROOT / "scripts/agentcore_plan.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = json.loads((ROOT / "infra/agentcore/deployment.example.json").read_text())
    with patch(
        "botocore.session.Session.create_client", side_effect=AssertionError("No AWS calls")
    ):
        plan = module.render(config)
    assert plan["cloud_execution"] is False
    gateways = [op["parameters"] for op in plan["operations"] if op["operation"] == "CreateGateway"]
    assert len(gateways) == 2
    assert all(g["authorizerType"] == "AWS_IAM" for g in gateways)
    tool_gateway = next(g for g in gateways if g.get("protocolType") == "MCP")
    assert tool_gateway["policyEngineConfiguration"]["mode"] == "ENFORCE"
    policies = [
        op["parameters"]["definition"]["policy"]["statement"]
        for op in plan["operations"]
        if op["operation"] == "CreatePolicy"
    ]
    assert len(policies) == 5
    assert not any(
        "create_reservation" in p or "refund" in p or "list_customer_records" in p for p in policies
    )
    targets = [
        op["parameters"] for op in plan["operations"] if op["operation"] == "CreateGatewayTarget"
    ]
    private = [t for t in targets if "mcp" in t["targetConfiguration"]]
    assert len(private) == 3
    assert all("privateEndpoint" in t for t in private)
    assert all(
        t["credentialProviderConfigurations"][0]["credentialProviderType"] == "API_KEY"
        for t in private
    )


def test_lambda_template_scopes_secret_and_uses_no_embedded_credential():
    template = json.loads((ROOT / "infra/agentcore/interceptor.template.json").read_text())
    resources = template["Resources"]
    fn = resources["Inspector"]["Properties"]
    assert fn["Timeout"] == 15 and fn["ReservedConcurrentExecutions"] == 5
    assert fn["Environment"]["Variables"]["AI_GUARD_MODE"] == "real"
    assert fn["Code"]["S3Bucket"] == {"Ref": "ArtifactBucket"}
    policy = resources["InterceptorRole"]["Properties"]["Policies"][0]["PolicyDocument"]
    secret_statement = next(
        s for s in policy["Statement"] if s.get("Action") == ["secretsmanager:GetSecretValue"]
    )
    assert secret_statement["Resource"] == {"Ref": "AIGuardSecretArn"}
