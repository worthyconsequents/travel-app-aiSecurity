import asyncio
import json
import re
import runpy
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.capability import fingerprint, sign, verify
from services.capability_transport import cleanup, incoming, outgoing


@pytest.fixture
def reference(monkeypatch):
    from services import db

    for key, value in {
        "TREND_CAPABILITY_TRANSPORT": "reference",
        "APP_MODE": "aws-demo",
        "ENABLE_AWS_TREND_GATEWAY": "true",
        "DEPLOYMENT_PROFILE": "trend-gateway",
        "MODEL_MODE": "mock",
    }.items():
        monkeypatch.setenv(key, value)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db.CapabilityReference.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "Session", factory)
    yield factory
    engine.dispose()


def token(tool, args, ttl=30):
    return sign(
        {"human": "alice", "fingerprint": fingerprint(tool, args), "expires": time.time() + ttl}
    )


def test_reference_hides_token_and_preserves_signed_scope(reference):
    from services.db import CapabilityReference

    args = {"booking_id": "booking-alice"}
    grant = token("get_my_bookings", args)
    wire = outgoing(args | {"gateway_capability": grant}, "get_my_bookings")
    assert re.fullmatch(r"btg_[a-f0-9]{32}", wire["gateway_capability"])
    assert grant not in json.dumps(wire)
    assert verify(incoming(wire["gateway_capability"]), "get_my_bookings", args)["human"] == "alice"
    for tool, changed in [
        ("get_my_bookings", {"booking_id": "booking-bob"}),
        ("cancel_reservation", args),
    ]:
        with pytest.raises(ValueError):
            verify(incoming(wire["gateway_capability"]), tool, changed)
    with reference() as db:
        row = db.scalar(select(CapabilityReference))
        assert row.id != wire["gateway_capability"] and len(row.id) == 64


def test_unknown_expired_and_raw_capabilities_fail_closed(reference):
    from services.db import CapabilityReference

    args = {"booking_id": "booking-alice"}
    grant = token("get_my_bookings", args)
    wire = outgoing(args | {"gateway_capability": grant}, "get_my_bookings")
    for value in ["", "invalid-test-capability", "btg_" + "f" * 32, grant]:
        with pytest.raises(ValueError):
            incoming(value)
    with reference.begin() as db:
        db.scalar(select(CapabilityReference)).expires = time.time() - 1
    with pytest.raises(ValueError):
        incoming(wire["gateway_capability"])
    cleanup()
    with reference() as db:
        assert db.scalar(select(CapabilityReference)) is None
    with pytest.raises(ValueError):
        outgoing(
            args | {"gateway_capability": token("get_my_bookings", args, ttl=-1)}, "get_my_bookings"
        )
    with pytest.raises(ValueError):
        outgoing(
            args | {"gateway_capability": token("get_my_bookings", args, ttl=600)},
            "get_my_bookings",
        )


def test_database_contents_cannot_forge_signature_authority(reference):
    from services.db import CapabilityReference

    args = {"booking_id": "booking-alice"}
    grant = token("get_my_bookings", args)
    wire = outgoing(args | {"gateway_capability": grant}, "get_my_bookings")
    with reference.begin() as db:
        row = db.scalar(select(CapabilityReference))
        row.token = grant[:-1] + ("0" if grant[-1] != "0" else "1")
    with pytest.raises(ValueError):
        verify(incoming(wire["gateway_capability"]), "get_my_bookings", args)


def test_reference_mode_requires_cloud_mock_activation(reference, monkeypatch):
    monkeypatch.setenv("APP_MODE", "local")
    with pytest.raises(RuntimeError):
        outgoing({}, "get_my_bookings")
    monkeypatch.setenv("APP_MODE", "aws-demo")
    monkeypatch.setenv("MODEL_MODE", "bedrock")
    with pytest.raises(RuntimeError):
        incoming("")


@pytest.mark.parametrize("service", ["travel-discovery", "reservations", "customer-payments"])
def test_reference_preserves_reviewed_tool_contract(reference, monkeypatch, service):
    from services.tool_catalog import fingerprint as contract_fingerprint

    monkeypatch.setenv("SERVICE", service)
    tools = asyncio.run(
        runpy.run_module("services.mcp_server", run_name="reference_contract_test")[
            "mcp"
        ].list_tools()
    )
    approved = json.loads(Path("services/approved_trend_catalog.json").read_text())
    for tool in tools:
        assert contract_fingerprint(tool) == contract_fingerprint(approved[tool.name])


def test_real_sdk_roundtrip_and_backend_rejection(reference):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("reference-test", stateless_http=True, json_response=True)

    @server.tool()
    def guarded_read(booking_id: str, gateway_capability: str = "") -> dict:
        claims = verify(incoming(gateway_capability), "guarded_read", {"booking_id": booking_id})
        return {"owner_verified": claims["human"] == "alice"}

    async def check():
        app = server.streamable_http_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                async with streamable_http_client(
                    "http://localhost:8000/mcp", http_client=client
                ) as (r, w, _):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        args = {"booking_id": "booking-alice"}
                        wire = outgoing(
                            args | {"gateway_capability": token("guarded_read", args)},
                            "guarded_read",
                        )
                        good = await session.call_tool("guarded_read", wire)
                        assert not good.isError and json.loads(good.content[0].text) == {
                            "owner_verified": True
                        }
                        missing = await session.call_tool("guarded_read", args)
                        assert missing.isError
                        changed = await session.call_tool(
                            "guarded_read", wire | {"booking_id": "booking-bob"}
                        )
                        assert changed.isError

    asyncio.run(check())
