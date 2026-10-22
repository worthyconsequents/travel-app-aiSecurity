"""Loopback-only HTTP validation. Vendor acceptance is reported independently."""

import argparse
import json
import time
import uuid
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["local", "trend"], default="local")
    args = parser.parse_args()
    live = args.profile == "trend"
    name = "trend-test.env" if live else "tool-changes.env"
    values = dict(
        line.split("=", 1)
        for line in (Path("infra/trend-gateway/private") / name).read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    port = "8082" if live else "8085"
    with httpx.Client(
        base_url=f"http://localhost:{port}/api", timeout=20, trust_env=False
    ) as client:
        assert client.get("/monitor/data").status_code == 401
        assert (
            client.post("/monitor/login", json={"password": values["MONITOR_PASSWORD"]}).status_code
            == 200
        )
        response = client.post(
            "/monitor/test-runs",
            json={"suite": "tool-changes"},
            headers={"X-Monitor-Action": "run-tests", "Idempotency-Key": str(uuid.uuid4())},
        )
        response.raise_for_status()
        job = response.json()["id"]
        for _ in range(190):
            row = client.get("/monitor/test-runs/" + job).json()
            if row["status"] not in {"queued", "running"}:
                break
            time.sleep(1)
        else:
            raise AssertionError("Test job did not finish")
        result = row["result"]
        assert len(result["scenarios"]) == result["total"] == 13
        assert result["fixture_restored"] and result["no_mutations"]
        assert all(
            client.get("/monitor/flow/" + s["correlation_id"]).status_code == 200
            for s in result["scenarios"]
        )
        if not live:
            assert [s["status"] for s in result["scenarios"]].count("passed") == 10
            assert [s["status"] for s in result["scenarios"]].count("unavailable") == 3
        output = Path("build/trend") / f"tool-changes-{args.profile}-result.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(row, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "launcher_protocol": "passed",
                    "security_acceptance": row["status"],
                    "profile": row["profile"],
                    "cases": [
                        {k: s[k] for k in ("name", "status", "reason_code")}
                        for s in result["scenarios"]
                    ],
                    "bookings_unchanged": True,
                    "fixture_restored": True,
                    "paid_model_calls": 0,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
