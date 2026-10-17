"""Read-only monitoring checks plus the six existing non-mutating attack fixtures."""

import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.getenv("MONITOR_BASE_URL", "http://localhost:8080")


def run():
    values = {}
    path = Path(__file__).resolve().parent.parent / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value
    password = os.getenv("MONITOR_PASSWORD") or values["MONITOR_PASSWORD"]
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def request(method, route, body=None, expected=200):
        time.sleep(0.1)  # Respect the published API rate limit during consecutive checks.
        req = urllib.request.Request(
            BASE + "/api" + route,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            response = opener.open(req, timeout=60)
        except urllib.error.HTTPError as error:
            response = error
        assert response.code == expected, (route, response.code, expected)
        if route.startswith("/monitor"):
            assert response.headers["Cache-Control"] == "no-store"
        return json.load(response)

    request("GET", "/monitor/data", expected=401)
    request("POST", "/session", {"identity": "admin"})
    request("GET", "/monitor/data", expected=401)
    request("GET", "/audit", expected=401)
    request("POST", "/scenarios/run", expected=401)
    request("POST", "/monitor/login", {"password": password})
    request("GET", "/monitor/session")
    result = request("POST", "/monitor/runs")
    assert result["passed"] and result["no_mutations"] and len(result["scenarios"]) == 6
    feed = request("GET", "/monitor/data")
    saved = next(row for row in feed["runs"] if row["id"] == result["run_id"])
    assert saved["status"] == "passed" and saved["result"]["scenarios"] == result["scenarios"]
    for scenario in result["scenarios"]:
        flow = request("GET", "/monitor/flow/" + scenario["correlation_id"])
        assert not flow["historical"]
        assert any(event["stage"] == "policy_decision" for event in flow["events"])
        assert not any(event["stage"] == "dispatch_started" for event in flow["events"])
        assert not flow["audits"][0]["downstream"]
    request("POST", "/session", {"identity": "alice"})
    chat = request("POST", "/chat", {"message": "Show booking-bob"})
    flow = request("GET", "/monitor/flow/" + chat["correlation_id"])
    stages = [event["stage"] for event in flow["events"]]
    core = [stage for stage in stages if not stage.startswith("inference_")]
    assert core == ["chat_received", "tool_requested", "policy_decision", "chat_completed"]
    if feed["profile"] == "agentcore-offline":
        assert stages.count("inference_started") == stages.count("inference_completed") == 2

    allowed = request("POST", "/chat", {"message": "Find stays in Kyoto"})
    allowed_flow = request("GET", "/monitor/flow/" + allowed["correlation_id"])
    observed = [event["stage"] for event in allowed_flow["events"]]
    assert (
        observed.index("policy_decision")
        < observed.index("dispatch_started")
        < observed.index("dispatch_completed")
    )
    assert allowed_flow["audits"][0]["outcome"] == "completed"
    assert password not in json.dumps(feed)
    request("POST", "/monitor/logout")
    request("GET", "/monitor/data", expected=401)
    print(
        json.dumps(
            {
                "base_url": BASE,
                "passed": True,
                "checks": [
                    "operator password required",
                    "customer/admin identities cannot bypass password",
                    "six saved attack outcomes",
                    "recorded policy traces; no denied dispatch",
                    "chat request-to-response trace",
                    "no secret in feed",
                    "logout",
                    "no booking mutations",
                ],
                "aws_calls": 0,
                "paid_model_calls": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    run()
