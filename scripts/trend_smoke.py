"""Explicit local-only Trend connectivity checks; no model calls or mutations."""

import asyncio
import json
import os
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from services.trend_transport import VirtualKeyAuth, canonical_catalog, tool_map


async def run():
    base = os.getenv("TREND_TEST_BASE_URL", "http://127.0.0.1:8082")
    assert urlsplit(base).hostname in {"localhost", "127.0.0.1"}, "Local testing only"
    url = os.environ["TREND_MCP_URL"]
    assert urlsplit(url).hostname in {"localhost", "127.0.0.1"}, "Use a loopback port-forward"
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    headers = {"Accept": "application/json, text/event-stream"}
    async with httpx.AsyncClient(trust_env=False, timeout=40) as client:
        for credential in (None, "deliberately-invalid-test-key"):
            h = headers | ({"Authorization": "Bearer " + credential} if credential else {})
            assert (await client.post(url, headers=h, json=payload)).status_code == 401
        health = (await client.get(base + "/api/health")).json()
        assert health["deployment_profile"] == "trend-gateway" and health["model"] == "mock"
        assert (await client.get(base + "/api/bookings")).status_code == 401
        assert (
            await client.post(base + "/api/session", json={"identity": "alice"})
        ).status_code == 200
        baseline = await client.get(base + "/api/bookings")
        baseline.raise_for_status()
        before = baseline.json()["result"]["bookings"]
        hotels = (await client.get(base + "/api/hotels?destination=Kyoto")).json()
        assert hotels["decision"] == "ALLOW" and len(hotels["result"]["hotels"]) == 4
        profile = (
            await client.post(
                base + "/api/tools/invoke", json={"tool": "get_customer_profile", "arguments": {}}
            )
        ).json()
        assert profile["decision"] == "ALLOW" and profile["result"]["id"] == "alice"
        denied = (
            await client.post(
                base + "/api/tools/invoke",
                json={"tool": "get_my_bookings", "arguments": {"booking_id": "booking-bob"}},
            )
        ).json()
        assert denied["decision"] == "DENY" and denied["reason_code"] == "OWNERSHIP_MISMATCH"
        after = (await client.get(base + "/api/bookings")).json()["result"]["bookings"]
        assert before == after
    async with httpx.AsyncClient(
        auth=VirtualKeyAuth(os.environ["TREND_VIRTUAL_KEY_FILE"]), trust_env=False, timeout=30
    ) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                catalog = (await session.list_tools()).tools
                count = sum(
                    len(canonical_catalog(s, catalog))
                    for s in ("travel-discovery", "reservations", "customer-payments")
                )
                assert count == 10
                remote = tool_map("travel-discovery")["search_hotels"]
                missing = await session.call_tool(remote, {"destination": "Kyoto"})
                assert missing.isError, "Backend accepted a call without signed capability"
                tampered = await session.call_tool(
                    remote,
                    {"destination": "Kyoto", "gateway_capability": "invalid-test-capability"},
                )
                assert tampered.isError, "Backend accepted a tampered capability"
    print(
        json.dumps(
            {
                "passed": True,
                "tools": count,
                "missing_and_invalid_virtual_key": 401,
                "three_service_read_paths": "passed",
                "unsigned_and_tampered_capability": "rejected",
                "cross_owner_denial": "application policy",
                "bookings_unchanged": True,
                "vendor_content_blocking": "not established by these checks",
                "paid_model_calls": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(run())
