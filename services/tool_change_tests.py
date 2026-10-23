"""Fixed, opt-in dynamic catalog experiment. Observations are not vendor approval."""

import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from services.agentcore.transport import deployment_profile
from services.db import Login, Session, uid
from services.telemetry import emit
from services.tool_catalog import compare
from services.tool_change_fixture import catalog

STEPS = [
    "baseline",
    "added",
    "schema",
    "description",
    "collision",
    "removed",
    "behavior",
    "application",
    "vendor-call",
    "notifications",
    "vision-one",
    "restore",
    "state",
]


def enabled():
    from services.fixture_scope import allowed_mode

    return (
        allowed_mode()
        and os.getenv("MODEL_MODE", "mock") == "mock"
        and os.getenv("TOOL_CHANGES_ENABLED") == "true"
    )


def plan():
    return [
        (
            k,
            {
                "application": "Application rejects a new tool",
                "vendor-call": "Independent gateway access test",
                "notifications": "Tool-change notification support",
                "vision-one": "Vision One console verification",
                "restore": "Restore fixture baseline",
                "state": "Synthetic bookings remain unchanged",
            }.get(k, f"Catalog experiment: {k}"),
            "data integrity" if k == "state" else "dynamic MCP experiment",
            "OBSERVED",
        )
        for k in STEPS
    ]


class Probe:
    def __init__(self):
        if not enabled():
            raise RuntimeError("Tool-change experiment is disabled")
        self.owner = uid()
        self.base = "http://tool-change-fixture:8000"
        self.control_key = Path(os.environ["TOOL_CHANGE_CONTROL_KEY_FILE"]).read_text().strip()
        self.upstream_key = Path(os.environ["TOOL_CHANGE_UPSTREAM_KEY_FILE"]).read_text().strip()
        self.live = deployment_profile() == "trend-gateway"
        self.mapping = None
        self.prefix = None
        if self.live:
            configuration = json.loads(Path(os.environ["TOOL_CHANGE_MAP_FILE"]).read_text())
            self.mapping = configuration["tools"]
            self.prefix = configuration["upstream_prefix"]
            if not isinstance(self.prefix, str) or not re.fullmatch(
                r"[A-Za-z0-9_.:/-]{1,200}", self.prefix
            ):
                raise ValueError("Explicit observed fixture namespace is required")
            expected = {"fixture_status", "fixture_new_tool", "search_hotels"}
            if (
                set(self.mapping) != expected
                or len(set(self.mapping.values())) != 3
                or any(
                    not isinstance(v, str) or v != self.prefix + k for k, v in self.mapping.items()
                )
            ):
                raise ValueError("Explicit unique fixture mapping is required")
        self.client = httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False)

    async def control(self, action, state="baseline"):
        response = await self.client.post(
            self.base + "/control/" + action,
            headers={"X-MCP-Service-Key": self.control_key},
            json={"owner": self.owner, "state": state},
        )
        response.raise_for_status()
        return response.json()

    @asynccontextmanager
    async def session(self):
        if self.live:
            from services.trend_transport import route

            url, _, auth = route()
            headers = {}
        else:
            url, auth = self.base + "/mcp/", None
            headers = {"X-MCP-Service-Key": self.upstream_key}
        async with httpx.AsyncClient(
            timeout=6, trust_env=False, follow_redirects=False, auth=auth, headers=headers
        ) as client:
            async with streamable_http_client(url, http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    yield session, initialized

    async def tools(self, session):
        result = []
        cursor = None
        for _ in range(10):
            page = await session.list_tools(cursor=cursor)
            for tool in page.tools:
                value = tool.model_dump(exclude_none=True)
                if self.mapping:
                    reverse = {v: k for k, v in self.mapping.items()}
                    if not value["name"].startswith(self.prefix):
                        continue  # Other travel upstreams are outside this experiment.
                    # Unknown names in this namespace remain visible to drift detection.
                    # This inventory never promotes them into the app's approved mapping.
                    value["name"] = reverse.get(
                        value["name"], value["name"].removeprefix(self.prefix)
                    )
                result.append(value)
            cursor = page.nextCursor
            if not cursor:
                return result
        raise ValueError("Catalog pagination exceeded fixture limit")


async def execute(progress):
    from services import test_cases
    from services.api import gateway_call
    from services.contracts import Call

    result = {
        "scenarios": [],
        "total": len(STEPS),
        "paid_model_calls": 0,
        "no_mutations": None,
        "fixture_restored": False,
        "vision_one_verified": False,
        "note": "Catalog observations and app decisions are separate from Vision One inventory and vendor ACL evidence.",
    }
    before = test_cases.snapshot()
    probe = None
    acquired = False
    login = Login(id=uid(), human="alice", agent="travel-assistant", expires=time.time() + 180)
    with Session.begin() as db:
        db.add(login)

    def event(correlation, stage, outcome):
        emit(correlation, stage, "alice", "travel-assistant", details={"outcome": outcome})

    def save(key, status, reason, evidence=None, correlation=None):
        correlation = correlation or uid()
        row = {
            "id": len(result["scenarios"]) + 1,
            "name": dict((x[0], x[1]) for x in plan())[key],
            "status": status,
            "passed": status == "passed",
            "decision": status.upper(),
            "source": "application authorization"
            if key == "application"
            else "data integrity"
            if key == "state"
            else "operator verification"
            if key == "vision-one"
            else "Trend MCP observation"
            if probe and probe.live
            else "local fixture",
            "observed_at": time.time(),
            "expected": {
                "baseline": "Approved baseline executes",
                "added": "New tool visible",
                "schema": "Schema drift detected",
                "description": "Description drift detected",
                "collision": "Distinct upstream identity",
                "removed": "Removal detected",
                "behavior": "Changed receipt with unchanged catalog",
                "application": "Unapproved tool denied",
                "vendor-call": "Unapproved tool denied by gateway",
                "notifications": "Notification delivery verified",
                "vision-one": "Inventory independently verified",
                "restore": "Fixture baseline restored",
                "state": "Bookings unchanged",
            }[key],
            "reason_code": reason,
            "correlation_id": correlation,
            "audit_id": "",
            "evidence": evidence or {},
        }
        result["scenarios"].append(row)
        emit(
            correlation,
            "test_case_completed",
            "alice",
            "travel-assistant",
            details={"outcome": status},
        )
        progress(result)

    try:
        progress(result)
        probe = Probe()
        await probe.control("acquire")
        acquired = True
        correlation = uid()
        event(correlation, "test_case_started", "baseline")
        async with probe.session() as (session, initialized):
            baseline = await probe.tools(session)
            delta = compare(catalog(), baseline)
            event(correlation, "catalog_observed", "baseline")
            event(correlation, "fixture_dispatch_started", "fixture_status")
            control = await session.call_tool(
                probe.mapping["fixture_status"] if probe.live else "fixture_status", {}
            )
            receipts = (await probe.control("observe"))["receipts"]
            good = (
                not any(delta[k] for k in ("added", "changed", "removed"))
                and not control.isError
                and len(receipts) == 1
            )
            save(
                "baseline",
                "passed" if good else "failed",
                "APPROVED_CONTROL_EXECUTED" if good else "BASELINE_NOT_ESTABLISHED",
                {"catalog": delta, "protocol": initialized.protocolVersion},
                correlation=correlation,
            )
            if not good:
                raise RuntimeError("Baseline unavailable")
            for state in ("added", "schema", "description", "collision", "removed", "behavior"):
                progress(result)
                correlation = uid()
                event(correlation, "test_case_started", state)
                await probe.control("change", state)
                event(correlation, "fixture_catalog_changed", state)
                same = await probe.tools(session)
                async with probe.session() as (fresh, _):
                    fresh_tools = await probe.tools(fresh)
                event(correlation, "catalog_observed", "same_and_fresh_sessions")
                expected = compare(catalog(), catalog(state))
                delta = compare(catalog(), fresh_tools)
                matched = all(
                    delta[k] == expected[k] for k in ("added", "removed", "changed")
                ) and not any(
                    compare(same, fresh_tools)[k] for k in ("added", "removed", "changed")
                )
                evidence = {"catalog": delta, "same_and_fresh_session_agree": same == fresh_tools}
                if state == "behavior":
                    event(correlation, "fixture_dispatch_started", "fixture_status")
                    call = await session.call_tool(
                        probe.mapping["fixture_status"] if probe.live else "fixture_status", {}
                    )
                    receipts = (await probe.control("observe"))["receipts"]
                    matched = matched and not call.isError and receipts[-1]["behavior"] == "changed"
                    evidence["behavior_changed_with_identical_catalog"] = matched
                save(
                    state,
                    "passed" if matched else "failed",
                    "CATALOG_OBSERVATION_MATCHED" if matched else "CATALOG_OBSERVATION_MISMATCH",
                    evidence,
                    correlation=correlation,
                )
            await probe.control("change", "added")
            correlation = uid()
            decision = await gateway_call(
                login, Call(tool="fixture_new_tool", arguments={}), correlation
            )
            save(
                "application",
                "passed"
                if decision.get("decision") == "DENY"
                and decision.get("reason_code") == "UNKNOWN_TOOL"
                else "failed",
                decision.get("reason_code", "APP_CHECK_FAILED"),
                correlation=correlation,
            )
            correlation = uid()
            event(correlation, "test_case_started", "independent_gateway_probe")
            count = len((await probe.control("observe"))["receipts"])
            event(correlation, "fixture_dispatch_started", "fixture_new_tool")
            call = await session.call_tool(
                probe.mapping["fixture_new_tool"] if probe.live else "fixture_new_tool", {}
            )
            after = (await probe.control("observe"))["receipts"]
            executed = any(r["tool"] == "fixture_new_tool" for r in after[count:])
            event(
                correlation, "fixture_receipt_checked", "executed" if executed else "not_executed"
            )
            if probe.live:
                # An MCP error alone cannot prove a vendor ACL decision.
                save(
                    "vendor-call",
                    "failed" if executed else "blocked",
                    "UNAPPROVED_TOOL_EXECUTED" if executed else "NO_EXECUTION_ACL_CAUSE_UNVERIFIED",
                    {
                        "backend_executed": executed,
                        "mcp_error": bool(call.isError),
                        "vendor_acl_verified": False,
                    },
                    correlation=correlation,
                )
            else:
                save(
                    "vendor-call",
                    "unavailable",
                    "NO_TREND_GATEWAY_ON_THIS_ROUTE",
                    {"backend_executed": executed},
                    correlation=correlation,
                )
            save(
                "notifications",
                "unavailable",
                "STATELESS_FIXTURE_USES_EXPLICIT_REFRESH",
                {
                    "advertised_list_changed": bool(
                        initialized.capabilities.tools
                        and initialized.capabilities.tools.listChanged
                    ),
                    "notification_delivery_verified": False,
                },
            )
            save("vision-one", "unavailable", "AWAITING_INDEPENDENT_CONSOLE_VERIFICATION")
    except asyncio.CancelledError:
        raise
    except Exception:
        # Do not persist raw SDK errors, headers, upstream text or credentials.
        completed = {s["name"] for s in result["scenarios"]}
        for key, name, _, _ in plan():
            if key not in {"restore", "state"} and name not in completed:
                save(key, "blocked", "DEPENDENCY_OR_BASELINE_UNAVAILABLE")
    finally:
        if probe:
            try:
                if acquired:
                    await probe.control("release")
                    result["fixture_restored"] = True
            except Exception:
                pass  # Server expires the lease and restores baseline independently after 120s.
            await probe.client.aclose()
        with Session.begin() as db:
            row = db.get(Login, login.id)
            if row:
                db.delete(row)
    save(
        "restore",
        "passed" if result["fixture_restored"] else "blocked",
        "FIXTURE_RELEASED" if result["fixture_restored"] else "RESTORE_UNCONFIRMED_TTL_120_SECONDS",
    )
    result["no_mutations"] = test_cases.snapshot() == before
    save("state", "passed" if result["no_mutations"] else "failed", "BOOKING_STATE_CHECK")
    statuses = {s["status"] for s in result["scenarios"]}
    status = next(
        (s for s in ("error", "failed", "blocked", "unavailable") if s in statuses), "passed"
    )
    result["passed"] = status == "passed"
    return result, status
