"""Fixed read-only capability comparison; run only inside the approved AWS lab."""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from services.capability import fingerprint, sign, verify
from services.contracts import Call
from services.db import Audit, Session, uid
from services.gateway import audit, context, policy
from services.telemetry import emit
from services.test_cases import snapshot
from services.trend_transport import canonical_catalog, route, tool_map


def now():
    return datetime.now(timezone.utc).isoformat()


def classify(result):
    text = " ".join(x.text for x in result.content if hasattr(x, "text")).lower()
    if result.isError:
        if "blocked by content policy (request)" in text:
            return "trend_request_content_block"
        if "blocked by content policy (response)" in text:
            return "trend_response_content_block"
        if "invalid gateway capability" in text:
            return "backend_capability_rejection"
        return "other_tool_rejection"
    return "tool_succeeded"


async def run():
    if not (
        os.getenv("APP_MODE") == "aws-demo"
        and os.getenv("ENABLE_AWS_TREND_GATEWAY") == "true"
        and os.getenv("MODEL_MODE") == "mock"
    ):
        raise RuntimeError("This diagnostic requires explicit AWS Trend mock mode")
    url, _, auth = route()
    before = snapshot()
    rows = []
    login = SimpleNamespace(human="alice", agent="travel-assistant")
    async with httpx.AsyncClient(auth=auth, trust_env=False, timeout=20) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                for server in ("reservations", "travel-discovery"):
                    canonical_catalog(server, tools)
                for server, tool, args in (
                    ("reservations", "get_my_bookings", {"booking_id": "booking-alice"}),
                    ("travel-discovery", "search_hotels", {"destination": "Kyoto"}),
                ):
                    signed = None
                    for variant in (
                        "omitted",
                        "invalid_literal",
                        "valid_signed",
                        "tampered_signature",
                    ):
                        correlation = uid()
                        with Session() as db:
                            c = context(db, login, Call(tool=tool, arguments=args), correlation)
                        decision = policy.evaluate(c)
                        if decision["decision"] != "ALLOW":
                            raise RuntimeError(
                                "Read-only diagnostic was not authorized by business policy"
                            )
                        send = dict(args)
                        valid_locally = None
                        if variant in {"valid_signed", "tampered_signature"}:
                            if signed is None:
                                signed = sign(
                                    {
                                        "tool": tool,
                                        "human": "alice",
                                        "agent": "travel-assistant",
                                        "resource": c["resource"],
                                        "amount": c["amount"],
                                        "approval_ref": None,
                                        "receipt_key": fingerprint(
                                            tool, {"human": "alice", "key": None, "approval": None}
                                        ),
                                        "fingerprint": fingerprint(tool, args),
                                        "expires": time.time() + 30,
                                    }
                                )
                                verify(signed, tool, args)
                            send["gateway_capability"] = signed
                            if variant == "tampered_signature":
                                send["gateway_capability"] = signed[:-1] + (
                                    "0" if signed[-1] != "0" else "1"
                                )
                        elif variant == "invalid_literal":
                            send["gateway_capability"] = "invalid-test-capability"
                        if "gateway_capability" in send:
                            try:
                                verify(send["gateway_capability"], tool, args)
                                valid_locally = True
                            except ValueError:
                                valid_locally = False
                        audit(c, decision, "authorized", True)
                        emit(
                            correlation,
                            "capability_probe_started",
                            "alice",
                            "travel-assistant",
                            tool,
                            c["audit_id"],
                            {"variant": variant},
                        )
                        row = {
                            "tool": tool,
                            "variant": variant,
                            "started_at_utc": now(),
                            "correlation_id": correlation,
                            "audit_id": c["audit_id"],
                            "signature_valid_locally": valid_locally,
                        }
                        try:
                            result = await asyncio.wait_for(
                                session.call_tool(tool_map(server)[tool], send), timeout=20
                            )
                            row["outcome"] = classify(result)
                        except Exception as exc:
                            row["outcome"] = "transport_or_execution_error"
                            row["error_type"] = type(exc).__name__
                        row["finished_at_utc"] = now()
                        with Session.begin() as db:
                            db.get(Audit, c["audit_id"]).outcome = row["outcome"]
                        emit(
                            correlation,
                            "capability_probe_completed",
                            "alice",
                            "travel-assistant",
                            tool,
                            c["audit_id"],
                            {"variant": variant, "outcome": row["outcome"]},
                        )
                        rows.append(row)
                        print(json.dumps({"event": "probe_case", **row}), flush=True)
    result = {
        "cases": rows,
        "booking_state_unchanged": snapshot() == before,
        "paid_model_calls": 0,
        "raw_capabilities_logged_by_probe": False,
        "note": "Controlled read-only diagnostic; content inspection and backend verification remain enabled. Correlate classifier details independently in Vision One.",
    }
    print(json.dumps({"event": "capability_probe_result", "result": result}), flush=True)


async def main():
    await asyncio.wait_for(run(), timeout=150)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({"event": "probe_error", "type": type(exc).__name__}), flush=True)
        raise SystemExit(1)
