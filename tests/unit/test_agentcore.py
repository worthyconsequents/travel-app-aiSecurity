import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from services.agentcore.inspection import AIGuardInspector, OfflineInspector, Verdict
from services.agentcore.interceptor import encode, handle
from services.agentcore.transport import (
    InferenceClient,
    SigV4Auth,
    aws_url,
    deployment_profile,
    mcp_route,
)


def event(namespace="http", response=False, content="A pleasant stay", **changes):
    if namespace == "http":
        body = (
            {"content": [{"type": "text", "text": content}]}
            if response
            else {
                "model": "offline-fixture",
                "messages": [{"role": "user", "content": content}],
                "stream": False,
            }
        )
        body.update(changes)
        packet = {
            "body": encode(body),
            **(
                {"statusCode": 200}
                if response
                else {"path": "/inference/v1/messages", "httpMethod": "POST"}
            ),
        }
    else:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            **(
                {"result": {"content": [{"type": "text", "text": content}]}}
                if response
                else {
                    "method": "tools/call",
                    "params": {"name": "search_hotels", "arguments": {"destination": content}},
                }
            ),
        }
        body.update(changes)
        packet = {"body": body, **({"statusCode": 200} if response else {})}
    return {
        "interceptorInputVersion": "1.0",
        namespace: {"gatewayRequest" if not response else "gatewayResponse": packet},
    }


@pytest.mark.parametrize("namespace", ["http", "mcp"])
@pytest.mark.parametrize("response", [False, True])
@pytest.mark.parametrize(
    ("text", "status"),
    [("nice trip", None), ("AIGUARD_TEST_BLOCK", 403), ("AIGUARD_TEST_UNAVAILABLE", 503)],
)
def test_both_contracts_and_directions(namespace, response, text, status):
    payload = event(namespace, response, text)
    before = json.dumps(payload)
    result = handle(payload, None, OfflineInspector())[namespace]
    assert json.dumps(payload) == before, "Inspection must not rewrite signed arguments"
    assert result.get("transformedGatewayResponse", {}).get("statusCode") == status


def test_response_null_request_and_tool_call_arguments_are_inspected():
    payload = event(response=True)
    payload["http"]["gatewayRequest"] = None
    body = {
        "content": [
            {
                "type": "tool_use",
                "id": "1",
                "name": "refund",
                "input": {"memo": "AIGUARD_TEST_BLOCK"},
            }
        ]
    }
    payload["http"]["gatewayResponse"]["body"] = encode(body)
    assert (
        handle(payload, None, OfflineInspector())["mcp" if "mcp" in payload else "http"][
            "transformedGatewayResponse"
        ]["statusCode"]
        == 403
    )


@pytest.mark.parametrize(
    "change",
    [
        {"stream": True},
        {"messages": []},
        {"messages": [{"role": "user", "content": [{"type": "image", "source": "anything"}]}]},
    ],
)
def test_unsupported_payloads_fail_before_inspection(change):
    inspector = Mock()
    result = handle(event(**change), None, inspector)
    assert result["http"]["transformedGatewayResponse"]["statusCode"] == 400
    inspector.inspect.assert_not_called()


@pytest.mark.parametrize(
    "body", ["not base64!!", base64.b64encode(b"[]").decode(), encode({"x": "a" * 70000})]
)
def test_invalid_encoding_and_size_are_rejected(body):
    payload = event()
    payload["http"]["gatewayRequest"]["body"] = body
    assert (
        handle(payload, None, OfflineInspector())["mcp" if "mcp" in payload else "http"][
            "transformedGatewayResponse"
        ]["statusCode"]
        == 400
    )


def test_missing_or_ambiguous_envelope_is_denied():
    for payload in [{}, {"interceptorInputVersion": "1.0", "http": {}, "mcp": {}}]:
        assert (
            handle(payload, None, OfflineInspector())["mcp" if "mcp" in payload else "http"][
                "transformedGatewayResponse"
            ]["statusCode"]
            == 400
        )


def test_credentials_not_sent_to_inspector_or_logs(capsys):
    payload = event("mcp")
    params = payload["mcp"]["gatewayRequest"]["body"]["params"]
    params["arguments"]["gateway_capability"] = "private-signed-grant"
    payload["mcp"]["gatewayRequest"]["headers"] = {"Authorization": "Bearer private-token"}
    inspector = Mock()
    inspector.inspect.return_value = Verdict("allow", 2)
    handle(payload, SimpleNamespace(aws_request_id="trusted-id"), inspector)
    scanned = inspector.inspect.call_args.args[0]
    logs = capsys.readouterr().out
    for secret in ["private-token", "private-signed-grant"]:
        assert secret not in scanned and secret not in logs
    assert "trusted-id" in logs and "search_hotels" not in logs


def test_unknown_verdict_and_inspector_failure_fail_closed():
    for outcome in [Verdict("unexpected"), RuntimeError("sensitive failure")]:
        inspector = Mock()
        if isinstance(outcome, Exception):
            inspector.inspect.side_effect = outcome
        else:
            inspector.inspect.return_value = outcome
        result = handle(event(), None, inspector)
        assert result["http"]["transformedGatewayResponse"]["statusCode"] == 503
        assert "sensitive" not in json.dumps(result)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.xdr.trendmicro.com/v3.0/aiSecurity/applyGuardrails",
        "https://evil.example/v3.0/aiSecurity/applyGuardrails",
        "https://api.xdr.trendmicro.com/v3.0/aiSecurity/applyGuardrails?token=x",
    ],
)
def test_inspection_endpoint_is_confined(url):
    with pytest.raises(ValueError):
        AIGuardInspector(url, "secret-arn", "travel")


def test_secret_ttl_refreshes_and_unknown_vendor_action_fails():
    clock = Mock(return_value=0)
    reader = Mock(side_effect=['{"apiKey":"first-key"}', '{"token":"rotated-key"}'])
    inspector = AIGuardInspector(
        "https://api.xdr.trendmicro.com/v3.0/aiSecurity/applyGuardrails",
        "secret-arn",
        "travel",
        reader,
        clock,
    )
    assert inspector.token() == "first-key"
    assert inspector.token() == "first-key"
    clock.return_value = 301
    assert inspector.token() == "rotated-key" and reader.call_count == 2
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"action":"unknown"}'
    inspector.opener.open = Mock(return_value=response)
    result = handle(event(), None, inspector)
    assert result["http"]["transformedGatewayResponse"]["statusCode"] == 503


def test_profiles_do_not_enable_aws_accidentally(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "agentcore-aws")
    monkeypatch.delenv("ENABLE_AWS_AGENTCORE", raising=False)
    with pytest.raises(RuntimeError, match="disabled"):
        deployment_profile()
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "unknown")
    with pytest.raises(ValueError):
        deployment_profile()


def test_namespacing_and_no_unknown_server_routing(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "agentcore-offline")
    url, prefix, auth = mcp_route("reservations")
    assert url == "http://agentcore-offline:8000/tools/mcp"
    assert prefix == "reservations___" and auth is None
    with pytest.raises(ValueError):
        mcp_route("evil.example/path")


@pytest.mark.parametrize(
    "url",
    [
        "http://id.gateway.bedrock-agentcore.us-west-2.amazonaws.com",
        "https://evil.example",
        "https://id.gateway.bedrock-agentcore.us-west-2.amazonaws.com?x=y",
    ],
)
def test_aws_origins_are_validated(url):
    with pytest.raises(ValueError):
        aws_url(url)


def test_offline_inference_has_no_fallback(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "agentcore-offline")
    attempts = []

    def fail(request):
        attempts.append(str(request.url))
        return httpx.Response(503, json={"reason_code": "INSPECTION_UNAVAILABLE"})

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            InferenceClient(transport=httpx.MockTransport(fail)).messages(
                {"messages": [{"role": "user", "content": "hello"}]}, "test"
            )
        )
    assert attempts == ["http://agentcore-offline:8000/inference/v1/messages"]


def test_live_inference_requires_separate_paid_opt_in(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "agentcore-aws")
    monkeypatch.setenv("ENABLE_AWS_AGENTCORE", "true")
    monkeypatch.delenv("ENABLE_PAID_INFERENCE", raising=False)
    with pytest.raises(RuntimeError, match="Paid inference"):
        asyncio.run(InferenceClient().messages({}, "test"))


def test_sigv4_signs_body_with_workload_credentials_only():
    from botocore.credentials import Credentials

    auth = SigV4Auth(
        "us-west-2", lambda: Credentials("offline-access", "offline-secret", "offline-session")
    )
    request = httpx.Request(
        "POST",
        "https://demo.gateway.bedrock-agentcore.us-west-2.amazonaws.com/mcp",
        json={"method": "tools/list"},
    )
    signed = next(auth.auth_flow(request))
    assert signed.headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")
    assert signed.headers["X-Amz-Security-Token"] == "offline-session"
    assert "bedrock-agentcore/aws4_request" in signed.headers["Authorization"]


@pytest.mark.parametrize("limit", [0, 513, True])
def test_request_token_budget_is_enforced(limit):
    inspector = Mock()
    result = handle(event(max_tokens=limit), None, inspector)
    assert result["http"]["transformedGatewayResponse"]["statusCode"] == 400
    inspector.inspect.assert_not_called()


def test_denied_inspection_is_audited_without_input(capsys):
    handle(
        event(content="AIGUARD_TEST_UNAVAILABLE sensitive-customer-text"), None, OfflineInspector()
    )
    log = capsys.readouterr().out
    assert "INSPECTION_UNAVAILABLE" in log and "sensitive-customer-text" not in log
