import asyncio
import time

from fastapi import FastAPI, Header, HTTPException
from jsonschema import Draft202012Validator

from services.auth import require_local, resolve
from services.capability import fingerprint, sign
from services.contracts import MUTATIONS, TOOLS, Call
from services.db import Approval, Audit, Booking, Quote, Receipt, Session, record, uid
from services.mcp_client import discover, invoke
from services.policy import ReferenceGateway
from services.telemetry import emit

require_local()
app = FastAPI(title="Reference enforcement gateway (not a commercial gateway)")
policy = ReferenceGateway()


@app.get("/health")
def health():
    return {"status": "ok", "service": "reference-gateway"}


def context(db, login, call, correlation):
    tool, args = call.tool, call.arguments
    resource = args.get("quote_id") or args.get("booking_id") or login.human
    owner, amount, valid = login.human, 0, True
    if tool == "create_reservation":
        row = db.get(Quote, str(resource))
        owner, amount = (row.human, row.amount) if row else (None, 0)
        valid = bool(row and row.expires > time.time())
    elif tool in {"cancel_reservation", "issue_mock_refund", "process_mock_payment"} or args.get(
        "booking_id"
    ):
        row = db.get(Booking, str(resource))
        owner, amount = (row.human, row.amount) if row else (None, 0)
        valid = (
            bool(row and row.status == "confirmed") if tool == "cancel_reservation" else bool(row)
        )
    approval = db.get(Approval, call.approval_ref) if call.approval_ref else None
    return {
        "human": login.human,
        "agent": login.agent,
        "tool": tool,
        "arguments": args,
        "owner": owner,
        "resource": str(resource),
        "resource_valid": valid,
        "amount": amount,
        "approval": record(approval) if approval else None,
        "audit_id": uid(),
        "correlation_id": correlation,
    }


def audit(c, decision, state="not_dispatched", downstream=False):
    # Never store freeform strings, arbitrary payloads, tokens, or model messages.
    args = {
        k: str(v)[:80]
        for k, v in c["arguments"].items()
        if k in {"hotel_id", "quote_id", "booking_id"} and isinstance(v, (str, int))
    }
    with Session.begin() as db:
        db.add(
            Audit(
                id=c["audit_id"],
                correlation_id=c["correlation_id"],
                human=c["human"],
                agent=c["agent"],
                tool=c["tool"],
                server=TOOLS.get(c["tool"], "unknown"),
                resource=c["resource"][:100],
                decision=decision["decision"],
                reason_code=decision["reason_code"],
                policy_id=decision["policy_id"],
                approval_state="present" if c["approval"] else "absent",
                arguments=args,
                downstream=downstream,
                outcome=state,
            )
        )


@app.get("/tools")
async def tools(authorization: str = Header(default="")):
    resolve(authorization.removeprefix("Bearer "))
    result = []
    for server in sorted(set(TOOLS.values())):
        result.extend(await discover(server))
    return {"tools": result}


@app.post("/invoke")
async def dispatch(
    call: Call, authorization: str = Header(default=""), x_correlation_id: str = Header(default="")
):
    login = resolve(authorization.removeprefix("Bearer "))
    correlation = x_correlation_id[:80] or uid()
    emit(correlation, "tool_requested", login.human, login.agent, call.tool)
    with Session() as db:
        c = context(db, login, call, correlation)
        # A successful idempotent replay returns the existing receipt without redispatch.
        receipt_key = fingerprint(
            call.tool,
            {"human": login.human, "key": call.idempotency_key, "approval": call.approval_ref},
        )
        prior = (
            db.get(Receipt, receipt_key)
            if call.idempotency_key and call.tool in MUTATIONS
            else None
        )
        if prior and prior.fingerprint == fingerprint(call.tool, call.arguments):
            d = {
                "decision": "ALLOW",
                "reason_code": "IDEMPOTENT_REPLAY",
                "policy_id": "reference-v1",
                "audit_id": c["audit_id"],
            }
            audit(c, d, "replayed")
            emit(
                correlation,
                "idempotent_replay",
                login.human,
                login.agent,
                call.tool,
                c["audit_id"],
                {"outcome": "replayed"},
            )
            return d | {"result": prior.result, "correlation_id": correlation}
    try:
        d = policy.evaluate(c)
    except Exception:
        d = {
            "decision": "DENY",
            "reason_code": "POLICY_UNAVAILABLE",
            "policy_id": "reference-v1",
            "audit_id": c["audit_id"],
        }
    emit(
        correlation,
        "policy_decision",
        login.human,
        login.agent,
        call.tool,
        c["audit_id"],
        {"decision": d["decision"], "reason_code": d["reason_code"]},
    )
    if d["decision"] != "ALLOW":
        audit(c, d)
        return d | {"correlation_id": correlation}
    if call.tool in MUTATIONS and not call.idempotency_key:
        d.update(decision="DENY", reason_code="IDEMPOTENCY_KEY_REQUIRED")
        emit(
            correlation,
            "enforcement_denied",
            login.human,
            login.agent,
            call.tool,
            c["audit_id"],
            {"decision": "DENY", "reason_code": "IDEMPOTENCY_KEY_REQUIRED"},
        )
        audit(c, d)
        return d | {"correlation_id": correlation}
    try:
        server = TOOLS[call.tool]
        schemas = await discover(server)
        schema = next(t["inputSchema"] for t in schemas if t["name"] == call.tool)
        Draft202012Validator(schema).validate(call.arguments)
        # Expand defaults so the signed arguments exactly match the backend invocation.
        args = dict(call.arguments)
        for k, prop in schema.get("properties", {}).items():
            if k not in args and "default" in prop:
                args[k] = prop["default"]
        grant = sign(
            {
                "tool": call.tool,
                "human": login.human,
                "agent": login.agent,
                "resource": c["resource"],
                "amount": c["amount"],
                "approval_ref": call.approval_ref,
                "receipt_key": receipt_key,
                "fingerprint": fingerprint(call.tool, args),
                "expires": time.time() + 30,
            }
        )
        audit(
            c, d, "authorized", True
        )  # Durable audit before dispatch; audit failure prevents dispatch.
        emit(correlation, "dispatch_started", login.human, login.agent, call.tool, c["audit_id"])
        attempts = 1 if call.tool in MUTATIONS else 2
        for attempt in range(attempts):
            try:
                result = await invoke(server, call.tool, args | {"gateway_capability": grant})
                break
            except Exception:
                if attempt + 1 == attempts:
                    raise
                await asyncio.sleep(0.1)
        with Session.begin() as db:
            db.get(Audit, c["audit_id"]).outcome = "completed"
        emit(
            correlation,
            "dispatch_completed",
            login.human,
            login.agent,
            call.tool,
            c["audit_id"],
            {"outcome": "completed"},
        )
        return d | {"result": result, "correlation_id": correlation}
    except Exception:
        emit(
            correlation,
            "tool_failed",
            login.human,
            login.agent,
            call.tool,
            c["audit_id"],
            {"outcome": "failed"},
        )
        with Session.begin() as db:
            row = db.get(Audit, c["audit_id"])
            if row:
                row.outcome = "downstream_error"
            else:
                d.update(decision="DENY", reason_code="SCHEMA_OR_TRANSPORT_ERROR")
                audit(c, d)
        raise HTTPException(
            502,
            {
                "decision": "DENY",
                "reason_code": "TOOL_UNAVAILABLE_OR_INVALID",
                "correlation_id": correlation,
            },
        )
