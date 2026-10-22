import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from services import mcp_client
from services.trend_transport import VirtualKeyAuth, canonical_catalog, route, tool_map


@pytest.fixture
def trend(monkeypatch, tmp_path):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "trend-gateway")
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("MODEL_MODE", "mock")
    monkeypatch.setenv("ENABLE_TREND_GATEWAY", "true")
    monkeypatch.setenv("TREND_MCP_URL", "http://trend-gateway-link:8081/")
    key = tmp_path / "virtual-key"
    key.write_text("local-test-virtual-key-1234567890")
    monkeypatch.setenv("TREND_VIRTUAL_KEY_FILE", str(key))
    mapping = tmp_path / "tool-map.json"
    mapping.write_text(
        json.dumps(
            {
                "search_hotels": "dannytran-discovery__search_hotels",
                "get_hotel_details": "dannytran-discovery__get_hotel_details",
                "search_flights": "dannytran-discovery__search_flights",
            }
        )
    )
    monkeypatch.setenv("TREND_TOOL_MAP_FILE", str(mapping))
    return key, mapping


def catalog():
    return [
        SimpleNamespace(
            name="dannytran-discovery__" + name,
            description="Untrusted description",
            inputSchema={
                "type": "object",
                "properties": {
                    "gateway_capability": {"type": "string"},
                    "destination": {"type": "string", "default": ""},
                },
                "required": ["gateway_capability"],
            },
        )
        for name in ("search_hotels", "get_hotel_details", "search_flights")
    ]


def test_explicit_activation_and_local_only(trend, monkeypatch):
    assert route()[0] == "http://trend-gateway-link:8081/"
    monkeypatch.setenv("ENABLE_TREND_GATEWAY", "false")
    with pytest.raises(RuntimeError):
        route()
    monkeypatch.setenv("ENABLE_TREND_GATEWAY", "true")
    monkeypatch.setenv("APP_MODE", "aws-demo")
    with pytest.raises(RuntimeError):
        route()


@pytest.mark.parametrize(
    "url",
    [
        "http://untrusted.example/",
        "http://trend-gateway-link:8081/mcp",
        "https://user:pass@example.com/",
        "https://example.com/?key=secret",
        "https://example.com/#fragment",
        "file:///tmp/key",
    ],
)
def test_url_confinement(trend, monkeypatch, url):
    monkeypatch.setenv("TREND_MCP_URL", url)
    with pytest.raises(ValueError):
        route()


def test_virtual_key_uses_bearer_and_refreshes_file(trend):
    key, _ = trend
    auth = VirtualKeyAuth(key)
    request = httpx.Request("POST", "http://trend-gateway-link:8081/")
    signed = next(auth.auth_flow(request))
    assert signed.headers["Authorization"] == "Bearer " + key.read_text()
    key.write_text("rotated-local-test-key-1234567890")
    assert next(auth.auth_flow(request)).headers["Authorization"] == "Bearer " + key.read_text()
    key.write_text("mixed notes\nnot a key")
    with pytest.raises(ValueError):
        next(auth.auth_flow(request))


def test_catalog_maps_exact_names_and_hides_capability(trend):
    result = canonical_catalog("travel-discovery", catalog())
    assert {t["name"] for t in result} == {"search_hotels", "get_hotel_details", "search_flights"}
    assert all(t["description"] == t["name"] for t in result)
    assert all("gateway_capability" not in t["inputSchema"]["properties"] for t in result)
    assert all("gateway_capability" not in t["inputSchema"]["required"] for t in result)


def test_missing_duplicate_or_changed_contract_fails_closed(trend):
    tools = catalog()
    for changed in (tools[:-1], tools + [tools[0]]):
        with pytest.raises(ValueError):
            canonical_catalog("travel-discovery", changed)
    tools[0].inputSchema["properties"].pop("gateway_capability")
    with pytest.raises(ValueError):
        canonical_catalog("travel-discovery", tools)


def test_ambiguous_unknown_or_partial_mapping_rejected(trend):
    _, mapping = trend
    for value in (
        {"search_hotels": "same", "get_hotel_details": "same"},
        {"unknown_tool": "remote"},
        {"search_hotels": "remote"},
    ):
        mapping.write_text(json.dumps(value))
        with pytest.raises(ValueError):
            tool_map("travel-discovery")


def test_trend_dispatch_preserves_capability_and_exact_name(trend):
    session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=SimpleNamespace(isError=False, structuredContent={"hotels": []})
        )
    )

    async def fake_session(server, operation):
        return await operation(session)

    arguments = {"destination": "Kyoto", "gateway_capability": "synthetic-signed-capability"}
    with patch.object(mcp_client, "with_session", new=fake_session):
        assert asyncio.run(mcp_client.invoke("travel-discovery", "search_hotels", arguments)) == {
            "hotels": []
        }
    session.call_tool.assert_awaited_once_with("dannytran-discovery__search_hotels", arguments)


def test_transport_failure_propagates_without_direct_backend_fallback(trend):
    with patch.object(
        mcp_client, "with_session", new=AsyncMock(side_effect=ConnectionError("offline"))
    ) as session:
        with pytest.raises(ConnectionError):
            asyncio.run(mcp_client.invoke("travel-discovery", "search_hotels", {}))
        assert session.await_count == 1


def test_unknown_tool_and_wrong_server_never_dispatch(trend):
    session = SimpleNamespace(call_tool=AsyncMock())

    async def fake_session(server, operation):
        return await operation(session)

    with patch.object(mcp_client, "with_session", new=fake_session):
        with pytest.raises(KeyError):
            asyncio.run(mcp_client.invoke("travel-discovery", "issue_mock_refund", {}))
    session.call_tool.assert_not_awaited()
