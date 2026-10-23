"""Explicit local Trend MCP transport; no direct-backend or model fallback."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx


class VirtualKeyAuth(httpx.Auth):
    def __init__(self, key_file):
        self.key_file = key_file

    def auth_flow(self, request):
        # Re-read the mounted key for each session so replacement requires no code change.
        value = Path(self.key_file).read_text().strip()
        if not 20 <= len(value) <= 16000 or any(c.isspace() for c in value):
            raise ValueError("Invalid Trend application virtual-key file")
        request.headers["Authorization"] = "Bearer " + value
        yield request


def route():
    mode = os.getenv("APP_MODE", "local")
    cloud = mode == "aws-demo" and os.getenv("ENABLE_AWS_TREND_GATEWAY") == "true"
    if (mode != "local" and not cloud) or os.getenv("ENABLE_TREND_GATEWAY") != "true":
        raise RuntimeError("Trend transport requires explicit local or AWS activation")
    if cloud and os.getenv("MODEL_MODE", "mock") != "mock":
        raise RuntimeError("AWS Trend tests require mock inference")
    value = os.environ["TREND_MCP_URL"]
    url = urlsplit(value)
    namespace = os.getenv("TREND_K8S_NAMESPACE", "")
    cloud_host = (
        cloud
        and re.fullmatch(r"dannytran-boring-travel[a-z0-9-]{1,40}", namespace)
        and url.hostname == f"trendai-gateway-gateway.{namespace}.svc.cluster.local"
        and url.port == 8081
    )
    if cloud and not cloud_host:
        raise ValueError("AWS Trend MCP must use this deployment's private cluster service")
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path != "/"
        or (
            url.scheme == "http"
            and not cloud_host
            and url.hostname not in {"trend-gateway-link", "localhost", "127.0.0.1"}
        )
    ):
        raise ValueError("Expected Trend MCP root URL; plain HTTP is restricted to the local link")
    return value, "", VirtualKeyAuth(os.environ["TREND_VIRTUAL_KEY_FILE"])


def tool_map(server):
    from services.contracts import TOOLS

    # Validate activation even when no network session is opened.
    route()
    mapping = json.loads(Path(os.environ["TREND_TOOL_MAP_FILE"]).read_text())
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("An explicit Trend tool mapping is required")
    if any(
        k not in TOOLS or not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,256}", v)
        for k, v in mapping.items()
    ) or len(set(mapping.values())) != len(mapping):
        raise ValueError("Invalid or ambiguous Trend tool mapping")
    selected = {key: value for key, value in mapping.items() if TOOLS[key] == server}
    expected = {key for key, value in TOOLS.items() if value == server}
    if set(selected) != expected:
        raise ValueError("Trend mapping does not cover this MCP server's contract")
    return selected


def canonical_catalog(server, tools):
    mapping = tool_map(server)
    catalog = {}
    for tool in tools:
        if tool.name in catalog:
            raise ValueError("Duplicate tool advertised by Trend")
        catalog[tool.name] = tool
    from services.tool_catalog import fingerprint

    approved = json.loads(Path(__file__).with_name("approved_trend_catalog.json").read_text())
    result = []
    for canonical, remote in mapping.items():
        if remote not in catalog:
            raise ValueError("Configured Trend tool is unavailable; no fallback used")
        tool = catalog[remote]
        if fingerprint(tool) != fingerprint(approved[canonical]):
            raise ValueError("Trend tool contract differs from the reviewed baseline")
        schema = dict(tool.inputSchema)
        properties = schema.get("properties", {})
        if properties.get("gateway_capability", {}).get("type") != "string":
            raise ValueError("Trend tool must preserve the signed-capability contract")
        schema["properties"] = {k: v for k, v in properties.items() if k != "gateway_capability"}
        schema["required"] = [k for k in schema.get("required", []) if k != "gateway_capability"]
        schema["additionalProperties"] = False
        # Use the canonical name as display text, not an upstream-controlled description.
        result.append({"name": canonical, "description": canonical, "inputSchema": schema})
    return result
