import asyncio
import copy
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import boto3
import httpx
import pytest
from botocore.stub import Stubber
from fastapi import HTTPException
from fastapi.testclient import TestClient

from scripts.trend_aws_config import TrendAWSConfig
from scripts.trend_bedrock import BedrockOption, addon, checklist, manifests
from services import bedrock_adapter as adapter
from services import bedrock_chat as chat


@pytest.fixture
def env(monkeypatch, tmp_path):
    ns = "dannytran-boring-travel-trend-lab01-01"
    key = tmp_path / "provider-key"
    key.write_text("test-only-" + "x" * 40)
    for k, v in {
        "APP_MODE": "aws-demo",
        "DEPLOYMENT_PROFILE": "trend-gateway",
        "ENABLE_AWS_BEDROCK": "true",
        "ENABLE_AWS_TREND_GATEWAY": "true",
        "ENABLE_PAID_INFERENCE": "true",
        "MODEL_MODE": "bedrock",
        "TREND_K8S_NAMESPACE": ns,
        "BEDROCK_MODEL_ID": "example.test-v1:0",
        "BEDROCK_PROVIDER_KEY_FILE": str(key),
        "TREND_VIRTUAL_KEY_FILE": str(key),
        "AWS_REGION": "us-east-1",
        "BEDROCK_MAX_REQUESTS_PER_HOUR": "60",
    }.items():
        monkeypatch.setenv(k, v)
    return {"Authorization": "Bearer " + key.read_text()}


def request_body():
    return {
        "model": adapter.PROVIDER_MODEL,
        "max_tokens": 400,
        "temperature": 0,
        "stream": False,
        "messages": [{"role": "user", "content": "Stays in Kyoto"}],
        "tools": [
            {
                "type": "function",
                "function": {"name": name, "description": name, "parameters": t["inputSchema"]},
            }
            for name, t in adapter.reviewed_tools().items()
        ],
    }


def tool_call(name="search_hotels", arguments=None, ident="tooluse_synthetic"):
    return {
        "id": ident,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps({"destination": "Kyoto"} if arguments is None else arguments),
        },
    }


def response(content=None):
    return {
        "output": {"message": {"role": "assistant", "content": content or [{"text": "Hello"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
        "metrics": {"latencyMs": 1},
    }


def test_adapter_invokes_converse_with_exact_bound_params_and_temporary_client(env, monkeypatch):
    body = adapter.Completion(**request_body())
    expected = adapter.translate(body, "example.test-v1:0")
    client = boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    monkeypatch.setattr(adapter, "bedrock_client", lambda region: client)
    with Stubber(client) as stub:
        stub.add_response("converse", response(), expected)
        with TestClient(adapter.create_app()) as http:
            result = http.post("/v1/chat/completions", headers=env, json=request_body())
        assert result.status_code == 200
        assert result.json()["usage"] == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
        stub.assert_no_pending_responses()
    assert expected["inferenceConfig"]["maxTokens"] == 400


@pytest.mark.parametrize(
    "case", ["disabled", "no-auth", "wrong-auth", "stream", "changed-schema", "mutation"]
)
def test_adapter_rejects_unsafe_requests_without_sdk_calls(env, monkeypatch, case):
    monkeypatch.setattr(adapter, "bedrock_client", lambda *a: pytest.fail("Unexpected SDK call"))
    body = request_body()
    headers = env
    if case == "disabled":
        monkeypatch.setenv("ENABLE_PAID_INFERENCE", "false")
    if case == "no-auth":
        headers = {}
    if case == "wrong-auth":
        headers = {"Authorization": "Bearer wrong"}
    if case == "stream":
        body["stream"] = True
    if case == "changed-schema":
        body["tools"][0]["function"]["parameters"] = {"$ref": "https://invalid.example/schema"}
    if case == "mutation":
        body["tools"][0]["function"]["name"] = "cancel_reservation"
    with TestClient(adapter.create_app()) as http:
        result = http.post("/v1/chat/completions", headers=headers, json=body)
        assert result.status_code in {401, 403, 422}
        assert "Stays in Kyoto" not in result.text


def test_adapter_normalizes_tool_use_and_correlates_result_ids(env):
    b = request_body()
    b["messages"] += [
        {"role": "assistant", "content": None, "tool_calls": [tool_call()]},
        {"role": "tool", "tool_call_id": "tooluse_synthetic", "content": "Synthetic result"},
    ]
    translated = adapter.translate(adapter.Completion(**b), "example.test-v1:0")
    assert (
        translated["messages"][-1]["content"][0]["toolResult"]["toolUseId"] == "tooluse_synthetic"
    )
    b["messages"][-1]["tool_call_id"] = "forged"
    with pytest.raises(ValueError):
        adapter.translate(adapter.Completion(**b), "example.test-v1:0")
    result = response(
        [
            {
                "toolUse": {
                    "toolUseId": "tooluse_synthetic",
                    "name": "search_hotels",
                    "input": {"destination": "Kyoto"},
                }
            }
        ]
    )
    result["stopReason"] = "tool_use"
    assert adapter.normalized(result, adapter.Completion(**request_body()))["choices"][0][
        "message"
    ]["tool_calls"]
    result["output"]["message"]["content"][0]["toolUse"]["name"] = "cancel_reservation"
    with pytest.raises(ValueError):
        adapter.normalized(result, adapter.Completion(**request_body()))


def test_sdk_failure_is_sanitized_and_hourly_limit_prevents_repeat(env, monkeypatch):
    client = boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    monkeypatch.setenv("BEDROCK_MAX_REQUESTS_PER_HOUR", "1")
    monkeypatch.setattr(adapter, "bedrock_client", lambda region: client)
    with Stubber(client) as stub:
        stub.add_client_error(
            "converse",
            service_error_code="AccessDeniedException",
            service_message="private-provider-error",
            expected_params=adapter.translate(
                adapter.Completion(**request_body()), "example.test-v1:0"
            ),
        )
        with TestClient(adapter.create_app()) as http:
            first = http.post("/v1/chat/completions", headers=env, json=request_body())
            second = http.post("/v1/chat/completions", headers=env, json=request_body())
        assert first.status_code == 502 and "private-provider-error" not in first.text
        assert second.status_code == 429
        stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    "variable", ["ENABLE_PAID_INFERENCE", "ENABLE_AWS_BEDROCK", "ENABLE_AWS_TREND_GATEWAY"]
)
def test_bedrock_requires_all_activation_gates(env, monkeypatch, variable):
    monkeypatch.setenv(variable, "false")
    with pytest.raises(RuntimeError):
        chat.require_bedrock_chat()


def test_model_profiles_and_external_ids_refused(env, monkeypatch):
    for model in (
        "us.example.test",
        "arn:aws:bedrock:us-east-1:123:inference-profile/x",
        "https://invalid",
    ):
        monkeypatch.setenv("BEDROCK_MODEL_ID", model)
        with pytest.raises(RuntimeError):
            adapter.deployment()


@pytest.mark.parametrize(
    "bad",
    [
        tool_call("cancel_reservation", {}),
        tool_call(arguments={"destination": "Kyoto", "human": "bob"}),
    ],
)
def test_chat_validates_entire_selection_before_dispatch(env, bad):
    schemas = {k: v["inputSchema"] for k, v in adapter.reviewed_tools().items()}
    with pytest.raises(Exception):
        chat.validate_selection({"tool_calls": [tool_call(), bad]}, schemas, set())


def test_real_loop_uses_trend_then_business_authorization_and_usage(env, monkeypatch):
    calls, posts, events = [], [], []

    async def gateway_call(login, call, correlation):
        calls.append(call)
        return {
            "decision": "ALLOW",
            "audit_id": "synthetic-audit",
            "result": {
                "hotels": [
                    {
                        "id": "h01",
                        "name": "A stay",
                        "destination": "Kyoto",
                        "price": 10000,
                        "rating": 4.5,
                        "description": "malicious prose excluded from model",
                    }
                ]
            },
        }

    monkeypatch.setitem(
        sys.modules,
        "services.api",
        SimpleNamespace(GATEWAY="http://gateway:8000", gateway_call=gateway_call),
    )
    monkeypatch.setattr(chat, "emit", lambda *args, **kwargs: events.append(kwargs))
    chat._limits.clear()

    def handler(request):
        if request.url.path == "/tools":
            return httpx.Response(200, json={"tools": list(adapter.reviewed_tools().values())})
        assert request.url.host.endswith(".svc.cluster.local") and request.url.port == 8080
        assert request.headers["authorization"] == env["Authorization"]
        body = json.loads(request.content)
        posts.append(body)
        assert body["model"].endswith("-bedrock-chat")
        output = (
            {"role": "assistant", "content": "Here are your stays"}
            if len(posts) > 1
            else {"role": "assistant", "content": None, "tool_calls": [tool_call()]}
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": output}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        chat.httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(handler)),
    )
    result = asyncio.run(
        chat.converse(
            "Stays in Kyoto",
            SimpleNamespace(id="session", human="alice", agent="travel-agent"),
            "cid",
        )
    )
    assert len(calls) == 1 and calls[0].tool == "search_hotels"
    assert len(posts) == 2 and result["model"] == "bedrock"
    assert "malicious prose" not in json.dumps(posts[1])
    assert result["usage"] == {"input_tokens": 40, "output_tokens": 10}
    assert events[-1]["details"]["input_tokens"] == 40


def option():
    return BedrockOption(
        TrendAWSConfig.load("infra/trend-aws/trend.example.env"), "example.test-v1:0", False, 60
    )


def test_addon_grants_one_model_to_adapter_only_and_uses_retained_generated_key():
    o = option()
    resources = addon(o)["Resources"]
    statements = resources["AdapterRole"]["Properties"]["Policies"][0]["PolicyDocument"][
        "Statement"
    ]
    assert statements == [
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel"], "Resource": [o.model_arn]}
    ]
    assert resources["Association"]["Properties"]["ServiceAccount"] == "bedrock-adapter"
    assert resources["ProviderKey"]["DeletionPolicy"] == "Retain"
    assert "SecretString" not in resources["ProviderKey"]["Properties"]
    assert "aws-cloudformation@3" in json.dumps(addon(o))


def test_manifest_and_checklist_keep_model_inference_disabled_and_private():
    o = option()
    image = (
        f"{o.base.account}.dkr.ecr.{o.base.region}.amazonaws.com/{o.base.name}-python@sha256:"
        + "a" * 64
    )
    items = manifests(o, image)["items"]
    dep = next(i for i in items if i["kind"] == "Deployment")
    spec = dep["spec"]["template"]["spec"]
    assert dep["spec"]["replicas"] == 1 and dep["spec"]["strategy"]["type"] == "Recreate"
    assert spec["serviceAccountName"] == "bedrock-adapter"
    env = {e["name"]: e["value"] for e in spec["containers"][0]["env"]}
    assert env["ENABLE_PAID_INFERENCE"] == "false"
    assert next(i for i in items if i["kind"] == "Service")["spec"]["type"] == "ClusterIP"
    text = checklist(o)
    assert "boring-travel-bedrock" in text and "No tenant API key" in text
    assert o.plan()["paid_calls"] == 0
    with pytest.raises(ValueError):
        manifests(o, "external/image:latest")


@pytest.mark.parametrize(
    "setting",
    [
        "BEDROCK_ENABLE_INFERENCE=yes",
        "BEDROCK_MAX_REQUESTS_PER_HOUR=0",
        "BEDROCK_MODEL_ID=us.example.test",
        "BEDROCK_MODEL_ID=vendor/model",
    ],
)
def test_option_rejects_unbounded_or_cross_region_settings(tmp_path, setting):
    file = tmp_path / "test.env"
    file.write_text(Path("infra/trend-aws/trend.example.env").read_text() + "\n" + setting + "\n")
    with pytest.raises(ValueError):
        BedrockOption.load(file)


def test_disabled_inference_and_no_console_ack_block_activation_before_aws(env):
    from scripts.trend_bedrock import activate

    class NoAWS:
        def __getattr__(self, name):
            pytest.fail("AWS accessed before activation gates")

    for o, ack in ((option(), True), (replace(option(), enabled=True), False)):
        with pytest.raises(ValueError):
            activate(o, "not-used", NoAWS(), ack)


def test_prepare_merges_credentials_and_excludes_adapter_from_additive_allow(monkeypatch, tmp_path):
    import base64

    from scripts import trend_bedrock as deploy

    monkeypatch.chdir(tmp_path)
    base = TrendAWSConfig.load(
        Path(__file__).resolve().parents[2] / "infra/trend-aws/trend.example.env"
    )
    o = BedrockOption(base, "example.test-v1:0", False, 60)
    image = (
        f"{base.account}.dkr.ecr.{base.region}.amazonaws.com/{base.name}-python@sha256:" + "a" * 64
    )
    secret_values, actions = {}, []
    monkeypatch.setattr(deploy, "check_cluster", lambda *args: None)
    monkeypatch.setattr(deploy, "provision", lambda *args: {"ProviderKeyArn": "synthetic-key-arn"})

    class Cloud:
        def client(self, service):
            if service == "bedrock":
                return SimpleNamespace(
                    get_foundation_model=lambda **kw: {
                        "modelDetails": {
                            "modelArn": o.model_arn,
                            "inferenceTypesSupported": ["ON_DEMAND"],
                        }
                    }
                )
            assert service == "secretsmanager"
            return SimpleNamespace(
                describe_secret=lambda **kw: {"Tags": deploy.secret_tags(base)},
                get_secret_value=lambda **kw: {"SecretString": "synthetic-provider-" + "z" * 30},
            )

    def kube(c, *args, **kw):
        actions.append((args, kw))
        if args[:3] == ("get", "deployment", "api"):
            return json.dumps({"spec": {"template": {"spec": {"containers": [{"env": []}]}}}})
        if args[:2] == ("get", "secret"):
            return json.dumps(
                {"data": {"mcp-boring-travel": base64.b64encode(b"original-mcp").decode()}}
            )
        if args[:2] == ("get", "networkpolicy"):
            return json.dumps({"spec": {"podSelector": {}}})
        return ""

    monkeypatch.setattr(deploy, "kubectl", kube)
    monkeypatch.setattr(
        deploy, "apply_secret", lambda c, name, data: secret_values.update({name: data})
    )
    result = deploy.prepare(o, image, Cloud(), True)
    assert result["prepared"] and not result["inference_enabled"]
    assert secret_values["gateway-upstream-credentials"]["mcp-boring-travel"] == "original-mcp"
    assert base.name + "-bedrock" in secret_values["gateway-upstream-credentials"]
    patch = next(args[-1] for args, kw in actions if args[:2] == ("patch", "networkpolicy"))
    assert json.loads(patch)["spec"]["podSelector"]["matchExpressions"][0]["values"] == [
        "bedrock-adapter"
    ]


@pytest.mark.parametrize("drift", [False, True])
def test_activation_and_rollback_fence_external_template_changes(monkeypatch, tmp_path, drift):
    from scripts import trend_bedrock as deploy

    base = TrendAWSConfig.load("infra/trend-aws/trend.example.env")
    o = BedrockOption(base, "example.test-v1:0", True, 60)
    image = (
        f"{base.account}.dkr.ecr.{base.region}.amazonaws.com/{base.name}-python@sha256:" + "a" * 64
    )
    before = {
        "metadata": {"labels": {"app": "api"}},
        "spec": {
            "containers": [
                {
                    "name": "api",
                    "image": "previous-image",
                    "env": [{"name": "OTHER_SETTING", "value": "preserved"}],
                }
            ]
        },
    }
    api = {"spec": {"template": copy.deepcopy(before)}}
    adapter_state = {"paid": False}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(deploy, "check_cluster", lambda *args: None)

    def kube(c, *args, **kw):
        if args[:3] == ("get", "deployment", "api"):
            return json.dumps(api)
        if args[:3] == ("get", "deployment", "bedrock-adapter"):
            return json.dumps(
                {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "image": image,
                                        "env": [{"name": "BEDROCK_MODEL_ID", "value": o.model_id}],
                                    }
                                ]
                            }
                        }
                    }
                }
            )
        if args[:2] == ("set", "env"):
            adapter_state["paid"] = args[-1].endswith("=true")
        if args[:3] == ("patch", "deployment", "api"):
            api["spec"]["template"] = json.loads(args[-1])["spec"]["template"]
        return ""

    monkeypatch.setattr(deploy, "kubectl", kube)
    assert deploy.activate(o, image, object(), True)["chat_backend"] == "bedrock"
    assert adapter_state["paid"]
    active_env = {
        e["name"]: e.get("value") for e in api["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert active_env["MODEL_MODE"] == "bedrock" and active_env["OTHER_SETTING"] == "preserved"
    if drift:
        api["spec"]["template"]["metadata"]["labels"]["external-change"] = "keep"
        with pytest.raises(ValueError, match="API changed"):
            deploy.rollback(o, object())
        assert api["spec"]["template"]["metadata"]["labels"]["external-change"] == "keep"
    else:
        deploy.rollback(o, object())
        assert api["spec"]["template"] == before
    assert not adapter_state["paid"]


def test_base_secret_sync_keeps_prepared_bedrock_provider_alias(monkeypatch, tmp_path):
    from scripts import trend_aws_bootstrap as bootstrap

    base = TrendAWSConfig.load("infra/trend-aws/trend.example.env")
    captured = {}

    class SM:
        def get_secret_value(self, SecretId):
            if SecretId.endswith("-discovery-fixture"):
                return {
                    "SecretString": json.dumps(
                        {"control-key": "fixture-control", "model-key": "mock-key"}
                    )
                }
            if SecretId.endswith("-bedrock-provider"):
                return {"SecretString": "synthetic-bedrock-provider-key"}
            return {"SecretString": json.dumps({"password": "synthetic-password-" + SecretId})}

    class Cloud:
        def __init__(self, *args):
            pass

        def status(self):
            return {
                "outputs": {
                    k + "SecretArn": k
                    for k in ("DatabasePassword", "Signing", "Monitor", "Upstream")
                }
            }

        def client(self, service):
            if service == "eks":
                return SimpleNamespace(
                    describe_cluster=lambda **kw: {"cluster": {"endpoint": "approved"}}
                )
            assert service == "secretsmanager"
            return SM()

    monkeypatch.setattr(bootstrap, "PRIVATE", tmp_path)
    monkeypatch.setattr(bootstrap, "AWS", Cloud)
    monkeypatch.setattr(
        bootstrap,
        "owned_secret_exists",
        lambda client, c, name: name.endswith(("-discovery-fixture", "-bedrock-provider")),
    )
    monkeypatch.setattr(
        bootstrap,
        "kubectl",
        lambda c, *a, **kw: json.dumps({"clusters": [{"cluster": {"server": "approved"}}]}),
    )
    monkeypatch.setattr(
        bootstrap, "apply_secret", lambda c, name, data: captured.update({name: data})
    )
    result = bootstrap.sync(base)
    assert result["runtime_synced"] and not result["virtual_key_synced"]
    gateway = captured["gateway-upstream-credentials"]
    assert gateway[base.name + "-bedrock"] == "synthetic-bedrock-provider-key"
    assert "mcp-boring-travel" in gateway and base.name + "-mock" in gateway


def test_prepare_resumes_only_its_recorded_review_change_set(monkeypatch, tmp_path):
    from scripts import trend_bedrock as deploy

    o = option()
    monkeypatch.chdir(tmp_path)
    pending = Path("build/trend-aws") / o.base.name / "bedrock-change-set.json"
    pending.parent.mkdir(parents=True)
    pending.write_text(
        json.dumps(
            {
                "deployment": o.base.name,
                "stack_id": "owned-stack",
                "change_set_id": "owned-change-set",
                "model_arn": o.model_arn,
            }
        )
    )

    class CFN:
        executed = False

        def describe_stacks(self, **kw):
            return {
                "Stacks": [
                    {
                        "StackId": "owned-stack",
                        "StackStatus": "CREATE_COMPLETE" if self.executed else "REVIEW_IN_PROGRESS",
                        "Tags": deploy.secret_tags(o.base),
                        "Outputs": [
                            {"OutputKey": "ModelArn", "OutputValue": o.model_arn},
                            {"OutputKey": "ProviderKeyArn", "OutputValue": "provider-key"},
                        ],
                    }
                ]
            }

        def get_waiter(self, name):
            return SimpleNamespace(wait=lambda **kw: None)

        def execute_change_set(self, ChangeSetName):
            assert ChangeSetName == "owned-change-set"
            self.executed = True

    cloud = CFN()
    aws = SimpleNamespace(client=lambda service: cloud)
    assert deploy.provision(o, aws, False)["review_required"]
    assert not cloud.executed
    assert deploy.provision(o, aws, True)["ProviderKeyArn"] == "provider-key"
    assert cloud.executed


@pytest.mark.parametrize("scenario", ["unknown-tool", "tool-limit"])
def test_model_failure_never_bypasses_auth_or_exceeds_tool_call_limit(env, monkeypatch, scenario):
    dispatched, model_calls = [], []

    async def gateway_call(login, call, correlation):
        dispatched.append(call.tool)
        return {"decision": "ALLOW", "audit_id": "synthetic", "result": {"hotels": []}}

    monkeypatch.setitem(
        sys.modules,
        "services.api",
        SimpleNamespace(GATEWAY="http://gateway:8000", gateway_call=gateway_call),
    )
    monkeypatch.setattr(chat, "emit", lambda *a, **kw: None)
    chat._limits.clear()

    def handler(request):
        if request.url.path == "/tools":
            return httpx.Response(200, json={"tools": list(adapter.reviewed_tools().values())})
        model_calls.append(1)
        selected = tool_call(ident="tooluse_" + str(len(model_calls)))
        if scenario == "unknown-tool":
            selected["function"] = {"name": "cancel_reservation", "arguments": "{}"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": None, "tool_calls": [selected]}}
                ]
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        chat.httpx,
        "AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            chat.converse(
                "Stays", SimpleNamespace(id="session", human="alice", agent="travel-agent"), "cid"
            )
        )
    assert error.value.status_code == 503
    assert len(dispatched) == (0 if scenario == "unknown-tool" else 3)
    assert len(model_calls) == (1 if scenario == "unknown-tool" else 4)
