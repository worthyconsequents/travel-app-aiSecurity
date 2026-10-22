"""Stop only the Trend return link, prove fail-closed booking, restore in finally."""

import json
import subprocess
from datetime import date, timedelta

import httpx

COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    "infra/trend-gateway/private/trend-test.env",
    "-p",
    "boring-travel-trend",
    "-f",
    "compose.yaml",
    "-f",
    "compose.trend-test.yaml",
]


def run():
    with httpx.Client(base_url="http://127.0.0.1:8082/api", timeout=30, trust_env=False) as client:

        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        assert call("GET", "/health")["deployment_profile"] == "trend-gateway"
        call("POST", "/session", json={"identity": "alice"})
        before = call("GET", "/bookings")["result"]["bookings"]
        start = date.today() + timedelta(days=60)
        quote = call(
            "POST",
            "/quotes",
            json={
                "hotel_id": "h01",
                "check_in": str(start),
                "check_out": str(start + timedelta(days=2)),
                "guests": 2,
            },
        )
        approval = call(
            "POST", "/approvals", json={"tool": "create_reservation", "resource": quote["id"]}
        )
        try:
            subprocess.run(COMPOSE + ["stop", "trend-gateway-link"], check=True)
            response = client.post(
                "/tools/invoke",
                json={
                    "tool": "create_reservation",
                    "arguments": {"quote_id": quote["id"]},
                    "approval_ref": approval["id"],
                    "idempotency_key": "outage-" + quote["id"],
                },
            )
            assert response.status_code == 503
            assert response.json()["detail"]["reason_code"] == "ENFORCEMENT_UNAVAILABLE"
            chat = client.post("/chat", json={"message": "Find stays in Kyoto"})
            assert chat.status_code == 503
        finally:
            subprocess.run(COMPOSE + ["up", "-d", "--wait", "trend-gateway-link"], check=True)
        after = call("GET", "/bookings")["result"]["bookings"]
        assert before == after, "Gateway outage created a booking or changed existing bookings"
        audit = call("GET", "/audit")["events"]
        assert any(
            e["reason_code"] == "ENFORCEMENT_UNAVAILABLE" and not e["downstream"] for e in audit
        )
        with httpx.Client(timeout=10, trust_env=False) as original:
            assert original.get("http://127.0.0.1:8080/api/health").status_code == 200
        print(
            json.dumps(
                {
                    "passed": True,
                    "approved_mutation_during_outage": 503,
                    "chat_during_outage": 503,
                    "no_booking_mutations": True,
                    "trend_link_restored": True,
                    "original_site_healthy": True,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    run()
