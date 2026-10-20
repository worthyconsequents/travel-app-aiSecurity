"""Offline contract, isolation and lifecycle tests; no AWS or paid vendor calls."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts import fleet_templates as templates
from scripts.aws_fleet import Fleet, main
from scripts.fleet_config import FleetConfig, read_env
from scripts.fleet_package import image_context

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config():
    base = FleetConfig.load(ROOT / ".env.example")
    return replace(
        base,
        account="123456789012",
        region="us-east-1",
        count=3,
        domain="example.com",
        hosted_zone="Z0123456789",
        certificate="arn:aws:acm:us-east-1:123456789012:certificate/11111111-1111-1111-1111-111111111111",
        allowed_cidr="203.0.113.1/32",
        secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:shared-key-AbCdEf",
        python_image="123456789012.dkr.ecr.us-east-1.amazonaws.com/demo-python@sha256:" + "a" * 64,
        frontend_image="123456789012.dkr.ecr.us-east-1.amazonaws.com/demo-frontend@sha256:"
        + "b" * 64,
        edge_image="123456789012.dkr.ecr.us-east-1.amazonaws.com/demo-edge@sha256:" + "c" * 64,
    )


@pytest.fixture
def base_outputs():
    return {
        "IngressSecretArn": "arn:aws:secretsmanager:us-east-1:123456789012:secret:copy-ingress-AbCdEf",
        "McpUrl": "https://dannytran-travel-lab01-01-mcp.example.com",
        "VpcId": "vpc-12345678901234567",
        "Subnet0": "subnet-12345678901234567",
        "Subnet1": "subnet-22345678901234567",
        "LatticeSecurityGroup": "sg-12345678901234567",
    }


def test_plan_has_stable_distinct_names_and_no_client(config):
    config.validate_deploy()
    with patch("boto3.Session", side_effect=AssertionError("Offline only")):
        plan = config.plan()
        assert plan["cloud_execution"] is False
        assert [x["name"] for x in plan["instances"]] == config.instances()
        assert config.name(1) == replace(config, count=20).name(1)
        assert config.namespace + "-shared" == plan["shared_stack"]
        assert len({x["url"] for x in plan["instances"]}) == 3


@pytest.mark.parametrize(
    "setting,value",
    [
        ("DEPLOYMENT_COUNT", "0"),
        ("DEPLOYMENT_COUNT", "21"),
        ("DEPLOYMENT_COUNT", "1.5"),
        ("DEPLOYMENT_PREFIX", "other-team"),
        ("DEPLOYMENT_ENV", "../prod"),
        ("DEPLOYMENT_ALLOWED_CIDR", "0.0.0.0/0"),
        ("ENABLE_PAID_INFERENCE", "yes"),
    ],
)
def test_invalid_config_rejected(tmp_path, setting, value):
    path = tmp_path / "fleet.env"
    path.write_text(f"{setting}={value}\n")
    with pytest.raises(ValueError):
        FleetConfig.load(path)


def test_env_is_data_and_duplicates_fail(tmp_path):
    path = tmp_path / ".env"
    path.write_text("UNUSED_TOKEN='$(touch should-never-exist)'\n")
    assert read_env(path)["UNUSED_TOKEN"] == "$(touch should-never-exist)"
    path.write_text("DEPLOYMENT_COUNT=1\nDEPLOYMENT_COUNT=3\n")
    with pytest.raises(ValueError, match="Duplicate"):
        read_env(path)


def test_missing_or_cross_account_settings_stop_before_aws(config, tmp_path):
    for changed in (
        replace(config, secret_arn=config.secret_arn.replace("123456789012", "999999999999")),
        replace(config, python_image=config.python_image.split("@")[0] + ":latest"),
        replace(config, certificate=""),
    ):
        with pytest.raises(ValueError):
            changed.validate_deploy()
    path = tmp_path / ".env"
    path.write_text("DEPLOYMENT_COUNT=3\n")
    with patch("boto3.Session", side_effect=AssertionError("No AWS")):
        assert main(["deploy", "--env-file", str(path)]) == 1
        assert main(["deploy", "--env-file", str(path), "--apply", "--acknowledge-costs"]) == 1
        assert main(["plan", "--env-file", str(path)]) == 0


def test_hosting_copies_do_not_share_state_or_key(config):
    first, second = templates.hosting(config, 1), templates.hosting(config, 2)
    a, b = first["Resources"], second["Resources"]
    assert a["Vpc"]["Properties"]["CidrBlock"] != b["Vpc"]["Properties"]["CidrBlock"]
    for secret in ("DatabaseSecret", "MonitorSecret", "SigningSecret", "IngressSecret"):
        assert a[secret]["Properties"]["Name"] != b[secret]["Properties"]["Name"]
        assert a[secret]["DeletionPolicy"] == "Retain"
    assert config.secret_arn not in json.dumps(first)
    db = a["Database"]["Properties"]
    assert db["StorageEncrypted"] and not db["PubliclyAccessible"]
    assert a["Database"]["DeletionPolicy"] == "Snapshot"
    assert (
        a["Service"]["Properties"]["NetworkConfiguration"]["AwsvpcConfiguration"]["AssignPublicIp"]
        == "DISABLED"
    )
    assert a["PublicListener"]["Properties"]["DefaultActions"][0]["Type"] == "authenticate-cognito"
    assert a["UserPool"]["Properties"]["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"]
    for value in a.values():
        if value["Type"] == "AWS::EC2::SecurityGroup":
            assert all(
                rule.get("CidrIp") != "0.0.0.0/0"
                for rule in value["Properties"]["SecurityGroupIngress"]
            )
    ports = [
        int(next(e["Value"] for e in c["Environment"] if e["Name"] == "PORT"))
        for c in a["Task"]["Properties"]["ContainerDefinitions"]
        if "Environment" in c
    ]
    assert len(ports) == len(set(ports))


def test_only_inspectors_share_exact_detection_secret(config, base_outputs):
    for index in range(1, 4):
        t = templates.agentcore(
            config, index, base_outputs, "example-bucket", "code.zip", "immutable-version"
        )
        r = t["Resources"]
        role = r["InspectorRole"]["Properties"]
        assert role["RoleName"] == config.name(index) + "-inspector"
        assert (
            role["Policies"][0]["PolicyDocument"]["Statement"][0]["Resource"] == config.secret_arn
        )
        assert config.secret_arn not in json.dumps(r["GatewayRole"])
        assert r["Inspector"]["Properties"]["Environment"]["Variables"][
            "AI_GUARD_APPLICATION_NAME"
        ] == config.name(index)
        assert r["Inspector"]["Properties"]["Code"]["S3ObjectVersion"] == "immutable-version"
        assert "ModelTarget" not in r
        assert "bedrock:InvokeModel" not in json.dumps(r)
        assert r["Tools"]["Properties"]["PolicyEngineConfiguration"]["Mode"] == "ENFORCE"
        permits = [v for v in r.values() if v["Type"] == "AWS::BedrockAgentCore::Policy"]
        assert len(permits) == 5
        assert "refund" not in json.dumps(permits) and "create_reservation" not in json.dumps(
            permits
        )
        targets = [v for v in r.values() if v["Type"] == "AWS::BedrockAgentCore::GatewayTarget"]
        assert len(targets) == 3
        assert all("PrivateEndpoint" in t["Properties"] for t in targets)


def test_template_sizes_and_all_references_resolve(config, base_outputs):
    for t in (
        templates.shared(config),
        templates.hosting(config, 1),
        templates.agentcore(config, 1, base_outputs, "example-bucket", "code.zip", "v1"),
    ):
        assert len(json.dumps(t, separators=(",", ":")).encode()) < 51200
        names = set(t["Resources"]) | set(t.get("Parameters", {}))

        def visit(value):
            if isinstance(value, dict):
                if "Ref" in value:
                    assert value["Ref"] in names or value["Ref"].startswith("AWS::")
                if "Fn::GetAtt" in value:
                    assert value["Fn::GetAtt"][0] in names
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(t)


def test_package_excludes_private_inputs(tmp_path):
    root, target = tmp_path / "repo", tmp_path / "context"
    root.mkdir()
    target.mkdir()
    for name in ("pyproject.toml", "uv.lock"):
        (root / name).write_text("test")
    for tree in ("services", "scripts", "frontend", "scenario-runner", "infra/aws-fleet"):
        (root / tree).mkdir(parents=True)
    (root / "services/ok.py").write_text("# allowed")
    (root / "frontend/.env.local").write_text("SECRET=private")
    (root / "services/key.pem").write_text("private")
    (root / "services/linked.py").symlink_to(root / "frontend/.env.local")
    image_context(root, target)
    assert (target / "services/ok.py").exists()
    assert not (target / "frontend/.env.local").exists()
    assert not (target / "services/linked.py").exists()
    assert not (target / "services/key.pem").exists()


def fake_fleet(config):
    fleet = object.__new__(Fleet)
    fleet.config = config
    fleet.state = {"stacks": {}, "instances": {}}
    fleet.persist = Mock()
    return fleet


def test_teardown_rejects_shared_and_ownership_before_writes(config):
    fleet = fake_fleet(config)
    fleet.lookup = Mock(side_effect=ValueError("Stack ownership differs"))
    fleet.client = Mock()
    with pytest.raises(ValueError):
        fleet.teardown(1, config.namespace + "-shared")
    fleet.lookup.assert_not_called()
    with pytest.raises(ValueError, match="ownership"):
        fleet.teardown(1, config.name(1))
    fleet.client.assert_not_called()


def test_stack_scope_rejects_foreign_tags_and_arn(config):
    fleet = fake_fleet(config)
    with pytest.raises(ValueError, match="ownership"):
        fleet.owned({"Tags": [], "StackId": "untrusted"})
    with pytest.raises(ValueError, match="outside"):
        fleet.owned(
            {
                "Tags": [
                    {"Key": "Project", "Value": "boring-travel-fleet"},
                    {"Key": "Namespace", "Value": config.namespace},
                ],
                "StackId": "arn:aws:cloudformation:us-east-1:999999999999:stack/name/id",
            }
        )


def test_aws_demo_cannot_use_default_auth_secrets(monkeypatch):
    from services.auth import require_local

    monkeypatch.setenv("APP_MODE", "aws-demo")
    monkeypatch.delenv("AWS_DEMO_EDGE_AUTH", raising=False)
    with pytest.raises(RuntimeError):
        require_local()
    monkeypatch.setenv("AWS_DEMO_EDGE_AUTH", "cognito-alb")
    monkeypatch.setenv("MCP_SIGNING_KEY", "x" * 48)
    monkeypatch.setenv("MONITOR_COOKIE_SECURE", "true")
    require_local()


def test_cloud_database_uses_tls_and_url_escapes_credentials(monkeypatch):
    from services.db import database_url

    monkeypatch.setenv("APP_MODE", "aws-demo")
    monkeypatch.setenv("DATABASE_HOST", "db.internal")
    monkeypatch.setenv("DATABASE_PASSWORD", "has@:/characters")
    url = database_url()
    assert url.password == "has@:/characters"
    assert url.query["sslmode"] == "verify-full"
    assert "has@:/characters" not in str(url)


def test_paid_inference_requires_explicit_model_project_and_enforces_it(config, base_outputs):
    with pytest.raises(ValueError, match="Paid inference"):
        replace(config, paid_inference=True).validate_deploy()
    paid = replace(
        config,
        paid_inference=True,
        model_id="bedrock-mantle/approved.model",
        model_resource="arn:aws:bedrock-mantle:us-east-1:123456789012:project/default",
    )
    paid.validate_deploy()
    r = templates.agentcore(paid, 1, base_outputs, "example-bucket", "code.zip", "v1")["Resources"]
    assert "ModelTarget" in r
    statement = next(
        s
        for s in r["GatewayRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
        if s["Action"] == ["bedrock-mantle:CreateInference"]
    )
    assert statement["Resource"] == paid.model_resource
    assert statement["Condition"]["StringEquals"]["bedrock-mantle:Model"] == "approved.model"


def test_target_prefix_is_per_copy(monkeypatch):
    from services.agentcore.transport import mcp_route

    monkeypatch.setenv("DEPLOYMENT_PROFILE", "agentcore-aws")
    monkeypatch.setenv("ENABLE_AWS_AGENTCORE", "true")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv(
        "AGENTCORE_TOOL_GATEWAY_URL",
        "https://example-1234567890.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
    )
    monkeypatch.setenv("AGENTCORE_TARGET_PREFIX", "dannytran-travel-lab01-01-")
    assert mcp_route("reservations")[1] == "dannytran-travel-lab01-01-reservations___"
    monkeypatch.setenv("AGENTCORE_TARGET_PREFIX", "../invalid")
    with pytest.raises(ValueError):
        mcp_route("reservations")


def stack_row(config, blueprint, parameters):
    from scripts.aws_fleet import checksum

    return {
        "StackId": f"arn:aws:cloudformation:{config.region}:{config.account}:stack/{config.name(1)}/unique-id",
        "StackName": config.name(1),
        "StackStatus": "UPDATE_COMPLETE",
        "Parameters": [{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
        "Tags": [
            {"Key": "Project", "Value": "boring-travel-fleet"},
            {"Key": "Namespace", "Value": config.namespace},
            {"Key": "Blueprint", "Value": checksum(blueprint)},
        ],
        "Outputs": [],
    }


def test_redeploy_bound_stack_is_noop_and_blueprint_drift_rejected(config):
    fleet = fake_fleet(config)
    cf = Mock()
    fleet.client = Mock(return_value=cf)
    blueprint = templates.hosting(config, 1)
    params = {
        "ToolGatewayUrl": "tool",
        "InferenceGatewayUrl": "inference",
        "ToolGatewayArn": "tool-arn",
        "InferenceGatewayArn": "inference-arn",
    }
    row = stack_row(config, blueprint, params)
    fleet.lookup = Mock(return_value=row)
    fleet.wait = Mock(return_value=row)
    fleet.ensure_stack(config.name(1), blueprint, params)
    cf.create_stack.assert_not_called()
    cf.update_stack.assert_not_called()
    different = templates.hosting(replace(config, allowed_cidr="203.0.113.2/32"), 1)
    with pytest.raises(ValueError, match="different blueprint"):
        fleet.ensure_stack(config.name(1), different, params)
    cf.update_stack.assert_not_called()


def test_only_initial_gateway_binding_may_update_existing_stack(config):
    fleet = fake_fleet(config)
    cf = Mock()
    fleet.client = Mock(return_value=cf)
    blueprint = templates.hosting(config, 1)
    params = {
        "ToolGatewayUrl": "tool",
        "InferenceGatewayUrl": "inference",
        "ToolGatewayArn": "tool-arn",
        "InferenceGatewayArn": "inference-arn",
    }
    blank = stack_row(config, blueprint, {k: "" for k in params})
    fleet.lookup = Mock(return_value=blank)
    fleet.wait = Mock(side_effect=[blank, stack_row(config, blueprint, params)])
    fleet.ensure_stack(config.name(1), blueprint, params)
    assert cf.update_stack.call_count == 1
    cf.create_stack.assert_not_called()


def test_reduced_count_deploy_does_not_delete_extra_instances(config, base_outputs):
    fleet = fake_fleet(replace(config, count=1))
    fleet.preflight = Mock()
    fleet.foundation = Mock(return_value={"ArtifactBucket": "example-bucket"})
    s3 = Mock()
    s3.get_paginator.return_value.paginate.return_value = []
    s3.put_object.return_value = {"VersionId": "v1"}
    fleet.client = Mock(return_value=s3)
    cloud = {
        "ToolGatewayUrl": "tool",
        "InferenceGatewayUrl": "inference",
        "ToolGatewayArn": "tool-arn",
        "InferenceGatewayArn": "inference-arn",
    }
    fleet.ensure_stack = Mock(
        side_effect=[base_outputs | {"AppUrl": "https://copy1.example.com"}, cloud, {}]
    )
    with patch("scripts.aws_fleet.package", return_value=b"offline-package"):
        fleet.deploy()
    assert [call.args[0] for call in fleet.ensure_stack.call_args_list] == [
        config.name(1),
        config.name(1) + "-agentcore",
        config.name(1),
    ]
    s3.delete_stack.assert_not_called()


def test_fleet_scope_lock_prevents_concurrent_writes(config, tmp_path):
    fleet = fake_fleet(config)
    fleet.directory = tmp_path
    with fleet.lock():
        with pytest.raises(ValueError, match="Another operation"):
            with fleet.lock():
                pytest.fail("Second lock should never be acquired")


def test_cloud_mock_chat_does_not_invoke_paid_inference(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from services.agent import converse

    monkeypatch.setenv("DEPLOYMENT_PROFILE", "agentcore-aws")
    monkeypatch.setenv("ENABLE_AWS_AGENTCORE", "true")
    monkeypatch.setenv("MODEL_MODE", "mock")
    with patch(
        "services.travel_assistant.converse", new=AsyncMock(return_value={"model": "mock"})
    ) as scripted:
        with patch(
            "services.agentcore.agent.converse",
            new=AsyncMock(side_effect=AssertionError("No paid model")),
        ):
            assert asyncio.run(converse("stays", Mock(), "correlation"))["model"] == "mock"
    scripted.assert_awaited_once()


def test_inspector_rejects_unconfigured_model_before_vendor(monkeypatch):
    from services.agentcore.interceptor import encode, handle

    monkeypatch.setenv("AI_GUARD_ALLOWED_MODEL", "per-copy-target/approved.model")
    inspector = Mock()
    payload = {
        "interceptorInputVersion": "1.0",
        "http": {
            "gatewayRequest": {
                "path": "/inference/v1/messages",
                "body": encode(
                    {"model": "other.model", "messages": [{"role": "user", "content": "hello"}]}
                ),
            }
        },
    }
    result = handle(payload, Mock(aws_request_id="offline-test"), inspector)
    assert result["http"]["transformedGatewayResponse"]["statusCode"] == 400
    inspector.inspect.assert_not_called()
