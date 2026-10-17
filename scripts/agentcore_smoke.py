"""Actual offline HTTP/MCP path checks; no AWS or live Trend service calls."""

import asyncio
import json
import os

import httpx
from sqlalchemy import select

from services.db import Booking, Session
from services.mcp_client import with_session


def snapshot():
    with Session() as db:
        return [
            (b.id, b.status, b.amount) for b in db.scalars(select(Booking).order_by(Booking.id))
        ]


async def run():
    assert os.environ["DEPLOYMENT_PROFILE"] == "agentcore-offline"
    before = snapshot()
    async with httpx.AsyncClient(timeout=30) as client:
        health = (await client.get("http://agentcore-offline:8000/health")).json()
        start = health["counters"]["inference_dispatches"]

        def payload(text):
            return {"messages": [{"role": "user", "content": text}], "model": "offline-fixture"}

        denied = await client.post(
            "http://agentcore-offline:8000/inference/v1/messages",
            json=payload("AIGUARD_TEST_BLOCK_INPUT"),
        )
        assert denied.status_code == 403
        assert (await client.get("http://agentcore-offline:8000/health")).json()["counters"][
            "inference_dispatches"
        ] == start
        denied = await client.post(
            "http://agentcore-offline:8000/inference/v1/messages",
            json=payload("offline-output-block-fixture"),
        )
        assert denied.status_code == 403
        denied = await client.post(
            "http://agentcore-offline:8000/inference/v1/messages",
            json=payload("AIGUARD_TEST_UNAVAILABLE"),
        )
        assert denied.status_code == 503

        # Test the actual aggregated MCP HTTP server directly. No capability is
        # needed to prove request inspection blocks BEFORE reaching the backend.
        async def call(session):
            return await session.call_tool(
                "travel-discovery___search_hotels",
                {"destination": "AIGUARD_TEST_BLOCK", "gateway_capability": ""},
            )

        mcp_before = (await client.get("http://agentcore-offline:8000/health")).json()["counters"][
            "mcp_dispatches"
        ]
        result = await with_session("travel-discovery", call)
        assert result.isError
        assert (await client.get("http://agentcore-offline:8000/health")).json()["counters"][
            "mcp_dispatches"
        ] == mcp_before
        # Real application chat runs the model-tool-model loop through the two
        # offline gateway contracts, while business authorization stays enforced.
        await client.post("http://localhost:8000/session", json={"identity": "alice"})
        normal = await client.post(
            "http://localhost:8000/chat", json={"message": "Find stays in Kyoto"}
        )
        normal.raise_for_status()
        assert normal.json()["deployment_profile"] == "agentcore-offline"
        assert normal.json()["calls"][0]["decision"] == "ALLOW"
        forged = await client.post(
            "http://localhost:8000/chat", json={"message": "offline-identity-fixture"}
        )
        forged.raise_for_status()
        assert forged.json()["calls"][0]["decision"] == "DENY"
    assert snapshot() == before, "Read/denied tests changed booking records"
    print(
        json.dumps(
            {
                "passed": True,
                "inspection": "offline markers, not live Trend detections",
                "checks": [
                    "input block before inference dispatch",
                    "output block after fixture inference",
                    "inspection outage fails closed",
                    "MCP input block before backend dispatch",
                    "authenticated model/tool loop",
                    "model identity spoof denied",
                    "no booking mutations",
                ],
                "aws_calls": 0,
                "paid_inference_calls": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(run())
