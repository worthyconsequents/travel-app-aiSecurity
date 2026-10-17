import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from services.capability import fingerprint, sign, verify
from services.policy import ReferenceGateway
from services.settings import require_mock


def context(**changes):
    return (
        dict(
            human="alice",
            agent="travel-assistant",
            tool="search_hotels",
            arguments={},
            owner="alice",
            resource="quote-test",
            amount=29000,
            approval=None,
            audit_id="audit-test",
            resource_valid=True,
        )
        | changes
    )


@pytest.mark.parametrize("mode", ["bedrock", "invalid", "", "openai"])
def test_paid_and_unknown_modes_rejected(monkeypatch, mode):
    monkeypatch.setenv("MODEL_MODE", mode)
    with pytest.raises(RuntimeError, match="mock only"):
        require_mock()


def test_mock_is_default(monkeypatch):
    monkeypatch.delenv("MODEL_MODE", raising=False)
    require_mock()


@pytest.mark.parametrize(
    ("changes", "decision", "reason"),
    [
        ({}, "ALLOW", "DISCOVERY_ALLOWED"),
        ({"tool": "unknown"}, "DENY", "UNKNOWN_TOOL"),
        ({"human": "unknown"}, "DENY", "UNKNOWN_IDENTITY"),
        ({"tool": "list_customer_records"}, "DENY", "BULK_DATA_DENIED"),
        ({"arguments": {"nested": [{"role": "admin"}]}}, "DENY", "IDENTITY_ASSERTION_REJECTED"),
        ({"tool": "get_my_bookings", "owner": "bob"}, "DENY", "OWNERSHIP_MISMATCH"),
        ({"tool": "issue_mock_refund"}, "DENY", "FINANCE_AGENT_REQUIRED"),
        ({"tool": "create_reservation"}, "REQUIRE_APPROVAL", "EXPLICIT_APPROVAL_REQUIRED"),
    ],
)
def test_policy_boundary(changes, decision, reason):
    result = ReferenceGateway().evaluate(context(**changes))
    assert (result["decision"], result["reason_code"]) == (decision, reason)


@pytest.mark.parametrize(
    "change",
    [{"amount": 1}, {"human": "bob"}, {"used": True}, {"expires": 0}, {"resource": "other"}],
)
def test_approval_cannot_be_reused_or_rescoped(change):
    approval = dict(
        human="alice",
        tool="create_reservation",
        resource="quote-test",
        amount=29000,
        used=False,
        expires=time.time() + 60,
    )
    result = ReferenceGateway().evaluate(
        context(tool="create_reservation", approval=approval | change)
    )
    assert result["decision"] == "DENY"


def test_capability_bound_to_tool_arguments_and_expiry():
    args = {"hotel_id": "h01"}
    grant = sign(
        {"expires": time.time() + 60, "fingerprint": fingerprint("get_hotel_details", args)}
    )
    verify(grant, "get_hotel_details", args)
    for tool, arguments, token in [
        ("get_hotel_details", {"hotel_id": "h02"}, grant),
        ("cancel_reservation", args, grant),
        ("get_hotel_details", args, grant + "0"),
        (
            "get_hotel_details",
            args,
            sign({"expires": 0, "fingerprint": fingerprint("get_hotel_details", args)}),
        ),
    ]:
        with pytest.raises(ValueError):
            verify(token, tool, arguments)


def test_gateway_failure_is_closed_and_audited(monkeypatch, tmp_path):
    import asyncio

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from services import api
    from services.contracts import Call
    from services.db import Audit, Base, Login

    engine = create_engine(f"sqlite:///{tmp_path}/fail-closed.db")
    Base.metadata.create_all(engine)
    session = sessionmaker(engine)
    monkeypatch.setattr(api, "Session", session)
    login = Login(
        id="test-session", human="alice", agent="travel-assistant", expires=time.time() + 60
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=httpx.ConnectError("offline"))):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                api.gateway_call(login, Call(tool="create_reservation"), "test-correlation")
            )
    assert exc.value.status_code == 503
    with session() as db:
        event = db.scalar(select(Audit))
        assert event.reason_code == "ENFORCEMENT_UNAVAILABLE"
        assert event.decision == "DENY" and not event.downstream
        assert event.correlation_id == "test-correlation"
    engine.dispose()
