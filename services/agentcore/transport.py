"""AgentCore clients: explicit offline selection, strict AWS origins, no fallback."""

import json
import os
import re
from urllib.parse import urlsplit

import httpx


def deployment_profile():
    profile = os.getenv("DEPLOYMENT_PROFILE", "local")
    if profile not in {"local", "agentcore-offline", "agentcore-aws"}:
        raise ValueError("Unknown deployment profile")
    if profile == "agentcore-aws" and os.getenv("ENABLE_AWS_AGENTCORE") != "true":
        raise RuntimeError(
            "AWS AgentCore is disabled; cost approval and explicit activation required"
        )
    return profile


def aws_url(value):
    parsed = urlsplit(value)
    pattern = r"[a-z0-9-]+\.gateway\.bedrock-agentcore\.[a-z0-9-]+\.amazonaws\.com"
    if (
        parsed.scheme != "https"
        or not re.fullmatch(pattern, parsed.hostname or "")
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Expected an AWS AgentCore gateway HTTPS endpoint")
    return value.rstrip("/")


class SigV4Auth(httpx.Auth):
    requires_request_body = True

    def __init__(self, region, credential_provider=None):
        self.region, self.credential_provider = region, credential_provider

    def auth_flow(self, request):
        from botocore.auth import SigV4Auth as Signer
        from botocore.awsrequest import AWSRequest

        if self.credential_provider:
            credentials = self.credential_provider()
        else:
            import boto3

            credentials = boto3.Session().get_credentials()
        if not credentials:
            raise RuntimeError("AWS credentials unavailable")
        frozen = credentials.get_frozen_credentials()
        signed = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers=dict(request.headers),
        )
        Signer(frozen, "bedrock-agentcore", self.region).add_auth(signed)
        request.headers.update(dict(signed.headers))
        yield request


def mcp_route(server):
    from services.contracts import TOOLS

    if server not in set(TOOLS.values()):
        raise ValueError("Unknown MCP server")
    profile = deployment_profile()
    if profile == "local":
        return f"http://{server}:8000/mcp", "", None
    prefix = server + "___"
    if profile == "agentcore-offline":
        return "http://agentcore-offline:8000/tools/mcp", prefix, None
    target_prefix = os.getenv("AGENTCORE_TARGET_PREFIX", "")
    if target_prefix and not re.fullmatch(r"[a-z][a-z0-9-]{1,50}-", target_prefix):
        raise ValueError("Invalid per-deployment target prefix")
    prefix = target_prefix + prefix
    url = aws_url(os.environ["AGENTCORE_TOOL_GATEWAY_URL"])
    if urlsplit(url).path != "/mcp":
        raise ValueError("Tool gateway URL must end in /mcp")
    return url, prefix, SigV4Auth(os.environ["AWS_REGION"])


class InferenceClient:
    def __init__(self, profile=None, transport=None):
        self.profile = profile or deployment_profile()
        self.transport = transport

    async def messages(self, payload, correlation):
        if payload.get("stream", False):
            raise ValueError("Streaming is disabled for inspected inference")
        if self.profile == "agentcore-offline":
            url, auth = "http://agentcore-offline:8000/inference/v1/messages", None
        elif self.profile == "agentcore-aws":
            if (
                os.getenv("ENABLE_PAID_INFERENCE") != "true"
                or os.getenv("MODEL_MODE") != "agentcore"
            ):
                raise RuntimeError("Paid inference is disabled")
            if deployment_profile() != "agentcore-aws":
                raise RuntimeError("AWS AgentCore is disabled")
            root = aws_url(os.environ["AGENTCORE_INFERENCE_GATEWAY_URL"])
            if urlsplit(root).path not in {"", "/"}:
                raise ValueError("Inference gateway URL must be the gateway origin")
            url, auth = root + "/inference/v1/messages", SigV4Auth(os.environ["AWS_REGION"])
        else:
            raise ValueError("Inference adapter requires an AgentCore profile")
        async with httpx.AsyncClient(
            auth=auth, transport=self.transport, timeout=20, trust_env=False, follow_redirects=False
        ) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"anthropic-version": "2023-06-01", "X-Correlation-ID": correlation},
            )
            response.raise_for_status()
            if len(response.content) > 65536:
                raise ValueError("Oversized inference response")
            result = json.loads(response.content)
            if not isinstance(result, dict) or not isinstance(result.get("content"), list):
                raise ValueError("Unsupported inference response")
            from services.agentcore.interceptor import validate_content

            validate_content(result["content"])
            return result
