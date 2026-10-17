import asyncio
import json
import time
from pathlib import Path

from sqlalchemy import select

from services.contracts import Call
from services.db import AttackRun, Audit, Booking, Hotel, Login, Quote, Session, record, uid

FIXTURES = Path(__file__).resolve().parent.parent / "scenario-runner/fixtures.json"


async def _execute_scenarios():
    from services.api import gateway_call

    fixtures = json.loads(FIXTURES.read_text())
    token = Login(id=uid(), human="alice", agent="travel-assistant", expires=time.time() + 120)
    q = Quote(
        id=uid(),
        human="alice",
        hotel_id="h01",
        check_in="2027-05-10",
        check_out="2027-05-12",
        guests=2,
        amount=29000,
        expires=time.time() + 120,
    )
    with Session.begin() as db:
        db.add_all([token, q])
        before = [record(b) for b in db.scalars(select(Booking).order_by(Booking.id))]
        injection = db.get(Hotel, "h04").description
        assert "list_customer_records" in injection
    results = []
    try:
        for fixture in fixtures:
            args = fixture["arguments"].copy()
            if fixture["id"] == 4:
                args["quote_id"] = q.id
            # The injection fixture forces the malicious model tool request to test
            # enforcement even when the deterministic model would ignore the payload.
            response = await gateway_call(token, Call(tool=fixture["tool"], arguments=args))
            with Session() as db:
                event = db.get(Audit, response["audit_id"])
                passed = (
                    response["decision"] == fixture["expected"]
                    and response["reason_code"] == fixture["reason"]
                    and not event.downstream
                    and event.agent == "travel-assistant"
                )
            # Inert, network-free comparison: simulated consequences only; no bypass
            # endpoint, external destination, credentials, or live data mutation.
            unprotected = {
                "decision": "SIMULATED_ALLOW",
                "effect": {
                    1: "synthetic records disclosed",
                    2: "Bob's synthetic booking disclosed",
                    3: "mock refund recorded",
                    4: "mock booking created",
                    5: "synthetic records copied to in-memory sink",
                    6: "forged role accepted",
                }[fixture["id"]],
            }
            results.append(
                {
                    "id": fixture["id"],
                    "name": fixture["name"],
                    "attack": {
                        "tool": fixture["tool"],
                        "arguments": args,
                        "source_hotel": fixture.get("source_hotel"),
                        "source_excerpt": injection if fixture["id"] == 1 else None,
                    },
                    "expected": fixture["expected"],
                    "decision": response["decision"],
                    "reason_code": response["reason_code"],
                    "audit_id": response["audit_id"],
                    "correlation_id": response["correlation_id"],
                    "passed": passed,
                    "unprotected": unprotected,
                }
            )
        with Session() as db:
            after = [record(b) for b in db.scalars(select(Booking).order_by(Booking.id))]
            assert before == after, "A denied attack changed a booking"
        return {
            "passed": all(x["passed"] for x in results),
            "scenarios": results,
            "comparison": "Isolated inert simulation; no unprotected network execution",
            "no_mutations": before == after,
        }
    finally:
        with Session.begin() as db:
            db.delete(db.get(Login, token.id))
            db.delete(db.get(Quote, q.id))


async def run_scenarios():
    from services.agentcore.transport import deployment_profile

    run_id = uid()
    with Session.begin() as db:
        db.add(AttackRun(id=run_id, profile=deployment_profile(), status="running", result={}))
    try:
        result = await _execute_scenarios()
        result["run_id"] = run_id
        with Session.begin() as db:
            row = db.get(AttackRun, run_id)
            row.result, row.finished = result, time.time()
            row.status = "passed" if result["passed"] else "failed"
        return result
    except Exception:
        with Session.begin() as db:
            row = db.get(AttackRun, run_id)
            row.status, row.finished = "error", time.time()
            row.result = {"error": "Scenario execution failed; check gateway availability."}
        raise


if __name__ == "__main__":
    result = asyncio.run(run_scenarios())
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
