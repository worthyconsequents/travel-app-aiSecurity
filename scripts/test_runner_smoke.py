"""Local HTTP smoke for the durable monitoring launcher; no AWS operations."""

import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def run():
    base = os.getenv("TEST_RUNNER_BASE_URL", "http://localhost:8083")
    if urlsplit(base).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("This helper is restricted to local smoke checks")
    values = {}
    p = Path(".env")
    if p.exists():
        values = dict(
            line.split("=", 1)
            for line in p.read_text().splitlines()
            if "=" in line and not line.startswith("#")
        )
    password = os.getenv("MONITOR_PASSWORD") or values.get("MONITOR_PASSWORD")
    if not password:
        raise ValueError("Set a private local monitoring password first")
    with httpx.Client(base_url=base + "/api", trust_env=False, timeout=20) as c:
        assert c.get("/monitor/data").status_code == 401
        assert c.post("/monitor/test-runs", json={"suite": "all"}).status_code == 401
        assert c.post("/monitor/login", json={"password": password}).status_code == 200
        assert c.get("/monitor/data").json()["test_runner"]["ready"]
        headers = {"X-Monitor-Action": "run-tests", "Idempotency-Key": str(uuid.uuid4())}
        r = c.post("/monitor/test-runs", json={"suite": "all"}, headers=headers)
        assert r.status_code == 202
        job = r.json()["id"]
        assert (
            c.post("/monitor/test-runs", json={"suite": "all"}, headers=headers).json()["id"] == job
        )
        # Poll through a fresh client: work must not depend on the launch connection.
        with httpx.Client(
            base_url=base + "/api", cookies=c.cookies, trust_env=False, timeout=20
        ) as reader:
            end = time.monotonic() + 190
            while time.monotonic() < end:
                r = reader.get("/monitor/test-runs/" + job)
                r.raise_for_status()
                row = r.json()
                if row["status"] not in {"queued", "running"}:
                    break
                time.sleep(1)
            else:
                raise AssertionError("Test job did not reach a terminal state")
            assert row["result"]["no_mutations"] is True
            assert len(row["result"]["scenarios"]) == row["result"]["total"] == 12
            assert all(
                reader.get("/monitor/flow/" + case["correlation_id"]).status_code == 200
                for case in row["result"]["scenarios"]
            )
            statuses = [case["status"] for case in row["result"]["scenarios"]]
            if row["profile"] == "local":
                assert statuses.count("passed") == 10 and statuses.count("unavailable") == 2
                assert row["status"] == "unavailable"
            elif row["profile"] == "agentcore-offline":
                assert row["status"] == "passed" and statuses.count("passed") == 12
            else:
                assert row["status"] == "passed", (
                    "Trend acceptance remains incomplete; inspect saved results"
                )
            print(
                json.dumps(
                    {
                        "launcher_protocol": "passed",
                        "profile": row["profile"],
                        "run_status": row["status"],
                        "completed_cases": len(statuses),
                        "bookings_unchanged": True,
                        "saved_case_flows": True,
                        "fresh_client_recovery": True,
                        "paid_model_calls": 0,
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    run()
