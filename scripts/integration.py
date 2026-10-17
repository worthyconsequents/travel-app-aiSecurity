"""Run inside the local API container; exercises real gateway -> MCP HTTP -> Postgres."""

import json
import os
from datetime import date, timedelta

import httpx


def run():
    checks = []
    with httpx.Client(base_url="http://localhost:8000", timeout=60) as client:

        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        assert request("GET", "/health")["model"] == "mock"
        assert client.get("/bookings").status_code == 401
        request("POST", "/session", json={"identity": "alice"})
        alice_cookie = client.cookies.get(os.getenv("SESSION_COOKIE_NAME", "waypoint_session"))
        with httpx.Client(timeout=30) as private:
            for server in ("gateway", "travel-discovery", "reservations", "customer-payments"):
                assert private.get(f"http://{server}:8000/health").json()["status"] == "ok"
            tools = private.get(
                "http://gateway:8000/tools", headers={"Authorization": f"Bearer {alice_cookie}"}
            )
            tools.raise_for_status()
            assert len(tools.json()["tools"]) == 10
        checks.append("All backend health endpoints and real MCP discovery: 10 tools")
        hotels = request("GET", "/hotels")["result"]["hotels"]
        assert len(hotels) == 12 and len({h["destination"] for h in hotels}) == 3
        assert len(request("GET", "/hotels?destination=Kyoto")["result"]["hotels"]) == 4
        assert request("GET", "/hotels/h01")["result"]["id"] == "h01"
        checks.append("Synthetic inventory, filtering, and details through MCP")

        def invoke(tool, arguments, **kwargs):
            return request(
                "POST", "/tools/invoke", json=dict(tool=tool, arguments=arguments, **kwargs)
            )

        profile = invoke("get_customer_profile", {})
        assert profile["result"]["id"] == "alice"
        own = request("GET", "/bookings")["result"]["bookings"]
        assert own and all(b["human"] == "alice" for b in own)
        denied = invoke("get_my_bookings", {"booking_id": "booking-bob"})
        assert denied["decision"] == "DENY"
        checks.append("Customer/payment MCP read and cross-customer isolation")
        start = date.today() + timedelta(days=30)
        quote = request(
            "POST",
            "/quotes",
            json={
                "hotel_id": "h01",
                "check_in": str(start),
                "check_out": str(start + timedelta(days=2)),
                "guests": 2,
            },
        )
        args = {"quote_id": quote["id"]}
        assert invoke("create_reservation", args)["decision"] == "REQUIRE_APPROVAL"
        grant = request(
            "POST", "/approvals", json={"tool": "create_reservation", "resource": quote["id"]}
        )
        created = invoke(
            "create_reservation", args, approval_ref=grant["id"], idempotency_key=quote["id"]
        )
        assert created["decision"] == "ALLOW", created
        replay = invoke(
            "create_reservation", args, approval_ref=grant["id"], idempotency_key=quote["id"]
        )
        assert (
            replay["result"] == created["result"] and replay["reason_code"] == "IDEMPOTENT_REPLAY"
        )
        assert (
            invoke(
                "create_reservation", args, approval_ref=grant["id"], idempotency_key="different"
            )["decision"]
            == "DENY"
        )
        booking_id = created["result"]["booking_id"]
        cancel_args = {"booking_id": booking_id}
        assert invoke("cancel_reservation", cancel_args)["decision"] == "REQUIRE_APPROVAL"
        cancel = request(
            "POST", "/approvals", json={"tool": "cancel_reservation", "resource": booking_id}
        )
        assert (
            invoke(
                "cancel_reservation",
                cancel_args,
                approval_ref=cancel["id"],
                idempotency_key=booking_id,
            )["result"]["status"]
            == "cancelled"
        )
        checks.append("Approved booking/cancellation, single-use grants, idempotent replay")
        chat = request("POST", "/chat", json={"message": "Find hotels in Lisbon"})
        assert chat["model"] == "mock" and chat["calls"][0]["decision"] == "ALLOW"
        request("POST", "/session", json={"identity": "bob"})
        bob = request("GET", "/bookings")["result"]["bookings"]
        assert bob and all(b["human"] == "bob" for b in bob)
        assert client.post("/scenarios/run").status_code == 403
        request("POST", "/session", json={"identity": "admin"})
        request("POST", "/monitor/login", json={"password": os.environ["MONITOR_PASSWORD"]})
        scenarios = request("POST", "/scenarios/run")
        assert (
            scenarios["passed"] and scenarios["no_mutations"] and len(scenarios["scenarios"]) == 6
        )
        audit = {e["id"]: e for e in request("GET", "/audit")["events"]}
        assert all(not audit[s["audit_id"]]["downstream"] for s in scenarios["scenarios"])
        checks.append("Mock chat and all six audited attack fixtures, no denied mutations")
    print(json.dumps({"passed": True, "checks": checks}, indent=2))


if __name__ == "__main__":
    run()
