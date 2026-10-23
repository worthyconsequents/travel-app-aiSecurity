import json
from dataclasses import replace
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from scripts.trend_aws_config import TrendAWSConfig
from scripts.trend_aws_manifests import bundle
from scripts.trend_aws_templates import foundation
from services import cloud_edge, trend_transport


@pytest.fixture
def config():
    return TrendAWSConfig.load("infra/trend-aws/trend.example.env")


def test_foundation_is_isolated_and_has_no_agentcore_or_public_database(config):
    t = foundation(config)
    r = t["Resources"]
    assert r["Cluster"]["Properties"]["Name"].startswith("dannytran-boring-travel-")
    assert not any("Bedrock" in x["Type"] for x in r.values())
    assert r["Database"]["Properties"]["PubliclyAccessible"] is False
    assert r["Database"]["Properties"]["StorageEncrypted"] is True
    assert r["Database"]["DeletionPolicy"] == "Retain"
    assert r["Nodes"]["Properties"]["ScalingConfig"]["MaxSize"] == 2
    ingress = r["IngressSecurity"]["Properties"]["SecurityGroupIngress"]
    assert ingress == [
        {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": config.operator_cidr}
    ]
    assert "17.11" in json.dumps(r["Database"]["Metadata"])
    assert len(json.dumps(t).encode()) < 51200


@pytest.mark.parametrize(
    "setting",
    [
        "ENABLE_PAID_INFERENCE=true",
        "DEPLOYMENT_COUNT=2",
        "DEPLOYMENT_PREFIX=travel",
        "AWS_TEST_BUDGET_USD=-1",
        "AWS_TEST_BUDGET_USD=NaN",
        "AWS_TEST_BUDGET_USD=0",
        "DEPLOYMENT_ALLOWED_CIDR=0.0.0.0/0",
    ],
)
def test_unsafe_or_unapproved_config_refused(tmp_path, setting):
    values = dict(
        line.split("=", 1)
        for line in __import__("pathlib")
        .Path("infra/trend-aws/trend.example.env")
        .read_text()
        .splitlines()
        if line and not line.startswith("#")
    )
    k, v = setting.split("=", 1)
    values[k] = v
    f = tmp_path / "test.env"
    f.write_text("\n".join(k + "=" + v for k, v in values.items()))
    with pytest.raises(ValueError):
        TrendAWSConfig.load(f)


def outputs():
    return {
        "DatabaseHost": "db.example.internal",
        "OperatorPoolId": "us-east-1_test",
        "OperatorClientId": "exampleclient",
        "PublicSubnets": "subnet-a,subnet-b",
        "IngressSecurityGroup": "sg-example",
        "CertificateArn": "arn:aws:acm:us-east-1:123456789012:certificate/example",
        "OperatorPoolArn": "arn:aws:cognito-idp:us-east-1:123456789012:userpool/us-east-1_test",
        "OperatorDomain": "example",
    }


def images(c):
    return {
        k: f"{c.account}.dkr.ecr.{c.region}.amazonaws.com/{c.name}-{k}@sha256:" + "a" * 64
        for k in ("python", "frontend", "edge")
    }


def test_bundle_uses_private_services_bounded_jobs_and_digest_images(config):
    value = bundle(config, outputs(), images(config))
    items = value["items"]
    jobs = [i for i in items if i["kind"] == "CronJob"]
    assert len(jobs) == 1 and jobs[0]["spec"]["concurrencyPolicy"] == "Forbid"
    assert jobs[0]["spec"]["jobTemplate"]["spec"]["activeDeadlineSeconds"] == 240
    pod = jobs[0]["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert "--one-shot" in pod["containers"][0]["command"]
    services = [i for i in items if i["kind"] == "Service"]
    assert [i["metadata"]["name"] for i in services if i["spec"]["type"] != "ClusterIP"] == ["edge"]
    assert any(
        i["kind"] == "NetworkPolicy" and i["metadata"]["name"] == "default-deny" for i in items
    )
    assert not any(i["kind"] == "Secret" for i in items)
    ingress = next(i for i in items if i["kind"] == "Ingress")
    assert ingress["metadata"]["annotations"]["alb.ingress.kubernetes.io/auth-type"] == "cognito"
    with pytest.raises(ValueError):
        bundle(config, outputs(), images(config) | {"python": "untrusted:latest"})


EXPECTED = (
    "us-east-1",
    "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/dannytran-boring-test/abc",
    "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test",
    "exampleclient",
)


def test_alb_verifies_signature_and_binds_to_exact_signer_issuer_and_client():
    key = ec.generate_private_key(ec.SECP256R1())
    headers = {"signer": EXPECTED[1], "iss": EXPECTED[2], "client": EXPECTED[3], "exp": 200}
    token = jwt.encode({"sub": "synthetic-operator"}, key, algorithm="ES256", headers=headers)
    identity = cloud_edge.validate_claims(token, key.public_key(), EXPECTED, now=100)
    assert len(identity) == 32 and "synthetic" not in identity
    for index in (1, 2, 3):
        wrong = list(EXPECTED)
        wrong[index] += "-another-copy"
        with pytest.raises(ValueError):
            cloud_edge.validate_claims(token, key.public_key(), wrong, now=100)
    with pytest.raises(ValueError):
        cloud_edge.validate_claims(token, key.public_key(), EXPECTED, now=201)
    with pytest.raises(jwt.InvalidSignatureError):
        cloud_edge.validate_claims(
            token, ec.generate_private_key(ec.SECP256R1()).public_key(), EXPECTED, now=100
        )


def test_forwarded_scheme_cannot_override_fixed_cloud_origin(monkeypatch):
    monkeypatch.setenv("APP_MODE", "aws-demo")
    monkeypatch.setenv("ENABLE_AWS_TREND_GATEWAY", "true")
    monkeypatch.setenv("AWS_APP_HOSTNAME", "boring-travel.example.com")
    request = SimpleNamespace(
        headers={"host": "boring-travel.example.com", "x-forwarded-proto": "http"}
    )
    assert cloud_edge.origin(request) == "https://boring-travel.example.com"
    request.headers["host"] = "another-copy.example.com"
    with pytest.raises(ValueError):
        cloud_edge.origin(request)


def test_cloud_trend_transport_has_no_external_or_other_namespace_fallback(monkeypatch, config):
    for k, v in {
        "APP_MODE": "aws-demo",
        "ENABLE_AWS_TREND_GATEWAY": "true",
        "ENABLE_TREND_GATEWAY": "true",
        "MODEL_MODE": "mock",
        "TREND_K8S_NAMESPACE": config.name,
        "TREND_VIRTUAL_KEY_FILE": "/not-read-by-route",
    }.items():
        monkeypatch.setenv(k, v)
    url = f"http://trendai-gateway-gateway.{config.name}.svc.cluster.local:8081/"
    monkeypatch.setenv("TREND_MCP_URL", url)
    assert trend_transport.route()[0] == url
    for unsafe in (
        "https://external.example.com/",
        "http://localhost:8081/",
        url.replace(config.name, "other-copy"),
    ):
        monkeypatch.setenv("TREND_MCP_URL", unsafe)
        with pytest.raises(ValueError):
            trend_transport.route()
    monkeypatch.setenv("TREND_MCP_URL", url)
    monkeypatch.setenv("MODEL_MODE", "bedrock")
    with pytest.raises(RuntimeError):
        trend_transport.route()


def test_plan_is_offline_and_budget_does_not_claim_hard_cap(config):
    result = config.plan()
    assert not result["aws_writes"] and not result["paid_inference"]
    assert result["cost_limit_is_not_a_hard_aws_cap"]
    assert replace(config, account="").plan()["account"] == ""


def test_only_vendor_gateway_gets_private_control_plane_egress(config):
    from scripts.trend_aws_manifests import with_discovery

    value = with_discovery(config, bundle(config, outputs(), images(config)), images(config))
    policies = {
        i["metadata"]["name"]: i["spec"] for i in value["items"] if i["kind"] == "NetworkPolicy"
    }
    rule = policies["gateway-control-plane"]
    assert rule["podSelector"]["matchLabels"] == {"app.kubernetes.io/instance": "trendai-gateway"}
    assert rule["egress"][0]["ports"] == [{"protocol": "TCP", "port": 443}]
    assert {x["ipBlock"]["cidr"] for x in rule["egress"][0]["to"]} == {
        "10.120.10.0/24",
        "10.120.11.0/24",
        "172.20.0.1/32",
    }
    assert not any(
        x.get("ipBlock", {}).get("cidr") == "0.0.0.0/0"
        for r in policies["same-copy"]["egress"]
        for x in r.get("to", [])
    )


@pytest.mark.parametrize("amount, expected", [("", None), ("101", "101"), ("250.50", "250.50")])
def test_planning_budget_is_optional_and_has_no_historical_operator_ceiling(tmp_path, amount, expected):
    from pathlib import Path

    source = Path("infra/trend-aws/trend.example.env").read_text()
    file = tmp_path / "budget.env"
    file.write_text(source.replace("AWS_TEST_BUDGET_USD=", "AWS_TEST_BUDGET_USD=" + amount))
    assert TrendAWSConfig.load(file).budget == expected


def test_secret_ownership_rejects_other_deployments_before_values_are_read(config):
    from scripts.trend_aws_bootstrap import owned_secret_exists, secret_tags

    class Missing(Exception):
        pass

    class Client:
        exceptions = SimpleNamespace(ResourceNotFoundException=Missing)

        def describe_secret(self, **kwargs):
            if self.tags is None:
                raise Missing()
            return {"Tags": self.tags}

    client = Client()
    client.tags = None
    assert not owned_secret_exists(client, config, "fixture")
    client.tags = secret_tags(config)
    assert owned_secret_exists(client, config, "fixture")
    for tags in ([], [{"Key": "Project", "Value": "boring-travel"}],
                 [{"Key": "Project", "Value": "other"},
                  {"Key": "Deployment", "Value": config.name}]):
        client.tags = tags
        with pytest.raises(ValueError, match="ownership mismatch"):
            owned_secret_exists(client, config, "fixture")


def test_secret_sync_checks_cluster_before_reading_or_writing_secrets(monkeypatch, config):
    from scripts import trend_aws_bootstrap as bootstrap

    class Cloud:
        def __init__(self, *args):
            pass

        def status(self):
            return {"outputs": {}}

        def client(self, service):
            assert service == "eks", "Secret access happened before cluster validation"
            return SimpleNamespace(describe_cluster=lambda **kw: {"cluster": {"endpoint": "approved"}})

    monkeypatch.setattr(bootstrap, "AWS", Cloud)
    monkeypatch.setattr(bootstrap, "kubectl", lambda *a, **kw: json.dumps(
        {"clusters": [{"cluster": {"server": "different-cluster"}}]}))
    with pytest.raises(ValueError, match="does not match"):
        bootstrap.sync(config)
