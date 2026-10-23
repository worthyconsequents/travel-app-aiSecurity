"""Response inspection must be demonstrated after an independent fixture receipt."""

import os

from services.fixture_scope import allowed_mode
from services.tool_change_tests import Probe


async def run():
    if not (
        allowed_mode()
        and os.getenv("APP_MODE") == "aws-demo"
        and os.getenv("TREND_RESPONSE_PROBE_ENABLED") == "true"
    ):
        return "unavailable", "RESPONSE_PROBE_NOT_CONFIGURED"
    probe = Probe()
    acquired = False
    matched = False
    try:
        await probe.control("acquire")
        acquired = True
        await probe.control("change", "response")
        async with probe.session() as (session, _):
            await session.list_tools()
            result = await session.call_tool(probe.mapping["fixture_status"], {})
        receipts = (await probe.control("observe"))["receipts"]
        text = " ".join(x.text for x in result.content if hasattr(x, "text"))
        matched = bool(
            result.isError
            and "blocked by content policy (response)" in text
            and len(receipts) == 1
            and receipts[0]["tool"] == "fixture_status"
        )
    finally:
        try:
            if acquired:
                await probe.control("release")
        finally:
            await probe.client.aclose()
    return (
        ("passed", "RESPONSE_CONTENT_POLICY_REJECTION_OBSERVED")
        if matched
        else ("failed", "RESPONSE_CONTENT_BLOCK_NOT_OBSERVED")
    )
