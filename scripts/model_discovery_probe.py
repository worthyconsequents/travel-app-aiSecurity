"""Fixed local mock-model routing experiment; no paid model or cloud deployment."""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from services.tool_change_tests import Probe
from services.trend_transport import VirtualKeyAuth


async def run():
    if os.getenv("MODEL_PROBE_ENABLED") != "true":
        raise RuntimeError("Explicit local model probe activation is required")
    probe = Probe()
    if not probe.live:
        raise RuntimeError("This experiment requires the local Trend route")
    key = Path(os.environ["MODEL_PROBE_KEY_FILE"]).read_text().strip()
    rows = []
    acquired = False
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "phases": rows,
        "paid_model_calls": 0,
        "fixture_restored": False,
        "inventory_verified": False,
        "note": "Verify Vision One inventory independently. Mock inference does not prove real-model behavior.",
    }
    stage = "acquire fixture"
    try:
        await probe.control("acquire")
        acquired = True
        async with httpx.AsyncClient(
            trust_env=False,
            timeout=15,
            follow_redirects=False,
            auth=VirtualKeyAuth(os.environ["TREND_VIRTUAL_KEY_FILE"]),
        ) as client:
            for state in ("baseline", "added"):
                stage = state + ": MCP catalog"
                await probe.control("change", state)
                async with probe.session() as (session, _):
                    tools = await probe.tools(session)
                    expected = {"fixture_status"} | (
                        {"fixture_new_tool"} if state == "added" else set()
                    )
                    if {t["name"] for t in tools} != expected:
                        raise RuntimeError("Unexpected fixture catalog")
                    payload = {
                        "model": "dannytran-tool-discovery-probe",
                        "stream": False,
                        "max_tokens": 32,
                        "temperature": 0,
                        "messages": [
                            {"role": "user", "content": "Local synthetic inventory probe."}
                        ],
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": t["name"],
                                    "description": t["description"],
                                    "parameters": t["inputSchema"],
                                },
                            }
                            for t in tools
                        ],
                    }
                    stage = state + ": model request"
                    response = await client.post(
                        "http://model-probe-link:8080/v1/chat/completions", json=payload
                    )
                    row = {
                        "state": state,
                        "tools_submitted": sorted(expected),
                        "http_status": response.status_code,
                    }
                    rows.append(row)
                    if response.status_code != 200:
                        row["status"] = "blocked"
                        break  # No guessed endpoints, repeated requests or direct fallback.
                    stage = state + ": validate mock response"
                    body = response.json()
                    calls = body["choices"][0]["message"]["tool_calls"]
                    if (
                        len(calls) != 1
                        or calls[0]["function"]["name"] not in expected
                        or json.loads(calls[0]["function"]["arguments"]) != {}
                    ):
                        raise RuntimeError("Unexpected mock tool call")
                    name = calls[0]["function"]["name"]
                    stage = state + ": MCP execution and receipts"
                    tool_result = await session.call_tool(probe.mapping[name], {})
                    row.update(selected_tool=name, mcp_error=bool(tool_result.isError))
                    async with httpx.AsyncClient(trust_env=False, timeout=5) as observer:
                        receipt = await observer.get(
                            "http://mock-model-provider:8000/probe-receipts",
                            headers={"Authorization": "Bearer " + key},
                        )
                        receipt.raise_for_status()
                        last = receipt.json()["calls"][-1]
                    row["mock_provider_received"] = (
                        last["tools"] == [t["name"] for t in tools] and last["selected"] == name
                    )
                    backend = (await probe.control("observe"))["receipts"]
                    row["backend_receipt_observed"] = bool(backend and backend[-1]["tool"] == name)
                    row["status"] = (
                        "passed"
                        if row["mock_provider_received"]
                        and row["backend_receipt_observed"]
                        and not tool_result.isError
                        else "failed"
                    )
    except Exception:
        result["error"] = "Probe stopped; raw transport/provider errors withheld."
        result["stopped_at"] = stage
    finally:
        if acquired:
            try:
                await probe.control("release")
                result["fixture_restored"] = True
            except Exception:
                result["restore_note"] = "Unconfirmed; fixture expires its lease after 120 seconds."
        await probe.client.aclose()
    result["routing_passed"] = (
        len(rows) == 2
        and all(row.get("status") == "passed" for row in rows)
        and result["fixture_restored"]
    )
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run())["routing_passed"] else 1)
