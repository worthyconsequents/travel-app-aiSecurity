"""Lambda entry point for AWS HTTP/inference and MCP interception contracts."""

import base64
import json
import os
import re

from services.agentcore.inspection import configured_inspector

MAX_BODY = 65536


def encode(value):
    return base64.b64encode(json.dumps(value).encode()).decode()


def decode(value):
    if not isinstance(value, str) or len(value) > 4 * MAX_BODY // 3 + 8:
        raise ValueError("Invalid encoded body")
    raw = base64.b64decode(value, validate=True)
    if len(raw) > MAX_BODY:
        raise ValueError("Body too large")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Object body required")
    return result


def scan_text(value, depth=0):
    if depth > 20:
        raise ValueError("Body too deep")
    if isinstance(value, dict):
        return "\n".join(
            f"{k}: {scan_text(v, depth + 1)}" for k, v in value.items() if k != "gateway_capability"
        )
    if isinstance(value, list):
        return "\n".join(scan_text(v, depth + 1) for v in value)
    if value is None:
        return ""
    return str(value)


def validate_content(content):
    if isinstance(content, str):
        return
    if not isinstance(content, list) or not content:
        raise ValueError("Unsupported model content")
    for block in content:
        if not isinstance(block, dict) or block.get("type") not in {
            "text",
            "tool_use",
            "tool_result",
        }:
            raise ValueError("Unsupported media or content block")
        kind = block["type"]
        if kind == "text" and not isinstance(block.get("text"), str):
            raise ValueError("Invalid text block")
        if kind == "tool_use" and (
            not isinstance(block.get("name"), str) or not isinstance(block.get("input"), dict)
        ):
            raise ValueError("Invalid tool call")
        if kind == "tool_use" and not isinstance(block.get("id"), str):
            raise ValueError("Tool call ID required")
        if kind == "tool_result":
            if not isinstance(block.get("tool_use_id"), str):
                raise ValueError("Tool result ID required")
            validate_content(block.get("content"))


def denied(namespace, reason, status=403, rpc_id=None):
    body = {"message": "Request could not pass inspection.", "reason_code": reason}
    if namespace == "mcp":
        body = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {
                "code": -32003,
                "message": "Inspection denied",
                "data": {"reason_code": reason},
            },
        }
    else:
        body = encode(body)
    return {
        "interceptorOutputVersion": "1.0",
        namespace: {
            "transformedGatewayResponse": {
                "statusCode": status,
                "body": body,
                "headers": {"content-type": "application/json"},
                **({"contentType": "application/json"} if namespace == "http" else {}),
            }
        },
    }


def audit(context, namespace, stage, decision, reason_code, reason_count=0):
    cid = str(getattr(context, "aws_request_id", "offline"))
    if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", cid):
        cid = "unavailable"
    print(
        json.dumps(
            {
                "stage": stage,
                "contract": namespace,
                "decision": decision,
                "reason_code": reason_code,
                "reason_count": reason_count,
                "invocation_id": cid,
            }
        )
    )


def passthrough(namespace, stage, packet):
    if namespace == "http":
        return {"interceptorOutputVersion": "1.0", "http": {}}
    # MCP requires explicit body preservation; an empty MCP output becomes an empty response.
    key = "transformedGatewayRequest" if stage == "REQUEST" else "transformedGatewayResponse"
    value = {"body": packet["body"]}
    if stage == "RESPONSE":
        value["statusCode"] = packet.get("statusCode", 200)
    return {"interceptorOutputVersion": "1.0", "mcp": {key: value}}


def handle(event, context, inspector):
    namespace = "mcp" if isinstance(event, dict) and "mcp" in event else "http"
    stage, rpc_id = "UNKNOWN", None
    try:
        if (
            not isinstance(event, dict)
            or event.get("interceptorInputVersion") != "1.0"
            or sum(k in event for k in ("mcp", "http")) != 1
        ):
            raise ValueError("Invalid interceptor envelope")
        envelope = event[namespace]
        response = envelope.get("gatewayResponse")
        stage = "RESPONSE" if response is not None else "REQUEST"
        packet = response if response is not None else envelope.get("gatewayRequest")
        if not isinstance(packet, dict) or packet.get("isStreamingResponse"):
            raise ValueError("Unsupported streaming or packet")
        if namespace == "http":
            body = decode(packet.get("body"))
            if stage == "REQUEST":
                allowed_model = os.getenv("AI_GUARD_ALLOWED_MODEL")
                if allowed_model and body.get("model") != allowed_model:
                    raise ValueError("Model not permitted for this deployment")
                if packet.get("path") != "/inference/v1/messages" or body.get("stream", False):
                    raise ValueError("Only buffered messages supported")
                limit = body.get("max_tokens", 400)
                if type(limit) is not int or not 1 <= limit <= 512:
                    raise ValueError("Token budget outside configured limit")
                messages = body.get("messages")
                if not isinstance(messages, list) or not messages:
                    raise ValueError("Messages required")
                for message in messages:
                    if not isinstance(message, dict) or message.get("role") not in {
                        "user",
                        "assistant",
                    }:
                        raise ValueError("Invalid message")
                    validate_content(message.get("content"))
                if "system" in body:
                    validate_content(body["system"])
            else:
                if not 200 <= int(packet.get("statusCode", 0)) < 300:
                    # Preserve failures; never turn an upstream error into success.
                    return {"interceptorOutputVersion": "1.0", "http": {}}
                validate_content(body.get("content"))
        else:
            body = packet.get("body")
            if not isinstance(body, dict) or len(json.dumps(body).encode()) > MAX_BODY:
                raise ValueError("Invalid MCP body")
            rpc_id = body.get("id")
            if stage == "REQUEST":
                method = body.get("method")
                if method in {"initialize", "notifications/initialized", "tools/list", "ping"}:
                    return passthrough(namespace, stage, packet)
                params = body.get("params", {})
                if (
                    method != "tools/call"
                    or not isinstance(params, dict)
                    or not isinstance(params.get("name"), str)
                    or not isinstance(params.get("arguments", {}), dict)
                ):
                    raise ValueError("Unsupported MCP request")
            elif body.get("jsonrpc") != "2.0" or not ("result" in body or "error" in body):
                raise ValueError("Invalid MCP response")
        text = scan_text(body)
        if not text.strip() or len(text.encode()) > MAX_BODY:
            raise ValueError("Inspection text missing or oversized")
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        audit(context, namespace, stage, "DENY", "UNSUPPORTED_PAYLOAD")
        return denied(namespace, "UNSUPPORTED_PAYLOAD", 400, rpc_id)
    try:
        verdict = inspector.inspect(text)
        if verdict.action not in {"allow", "block"}:
            raise ValueError("Unknown verdict")
    except Exception:
        audit(context, namespace, stage, "DENY", "INSPECTION_UNAVAILABLE")
        return denied(namespace, "INSPECTION_UNAVAILABLE", 503, rpc_id)
    # No raw reasons: vendor reason strings may echo sensitive input.
    audit(
        context,
        namespace,
        stage,
        verdict.action.upper(),
        "AI_GUARD_BLOCK" if verdict.action == "block" else "CONTENT_ALLOWED",
        verdict.reason_count,
    )
    if verdict.action == "block":
        return denied(namespace, "AI_GUARD_BLOCK", 403, rpc_id)
    return passthrough(namespace, stage, packet)


_inspector = None


def lambda_handler(event, context):
    global _inspector
    try:
        if _inspector is None:
            _inspector = configured_inspector()
        return handle(event, context, _inspector)
    except Exception:
        namespace = "mcp" if isinstance(event, dict) and "mcp" in event else "http"
        audit(context, namespace, "UNKNOWN", "DENY", "INSPECTION_UNAVAILABLE")
        return denied(namespace, "INSPECTION_UNAVAILABLE", 503)
