"""Local AWS contract simulator. Not AWS AgentCore or real AI Guard detection."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from services.agentcore.inspection import OfflineInspector
from services.agentcore.interceptor import decode, encode, handle
from services.contracts import TOOLS
from services.mcp_client import invoke
from services.travel_assistant import plan, present

mcp = FastMCP(
    "AgentCore offline contract simulator",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["agentcore-offline:*", "localhost:*", "127.0.0.1:*"],
        allowed_origins=[],
    ),
)
inspector = OfflineInspector()
counters = {
    "mcp_dispatches": 0,
    "inference_dispatches": 0,
    "request_denials": 0,
    "response_denials": 0,
}


def check(namespace, stage, body, path="/inference/v1/messages", correlation="offline"):
    packet = {"body": encode(body) if namespace == "http" else body}
    packet.update(
        {"path": path, "httpMethod": "POST"} if stage == "REQUEST" else {"statusCode": 200}
    )
    envelope = {"gatewayRequest" if stage == "REQUEST" else "gatewayResponse": packet}
    result = handle(
        {"interceptorInputVersion": "1.0", namespace: envelope},
        SimpleNamespace(aws_request_id=correlation),
        inspector,
    )
    denial = result[namespace].get("transformedGatewayResponse")
    if denial:
        counters["request_denials" if stage == "REQUEST" else "response_denials"] += 1
    return denial


async def dispatch(tool, args, capability):
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args | {"gateway_capability": capability}},
    }
    denial = check("mcp", "REQUEST", request)
    if denial:
        raise ValueError(denial["body"]["error"]["data"]["reason_code"])
    counters["mcp_dispatches"] += 1
    result = await invoke(TOOLS[tool], tool, args | {"gateway_capability": capability})
    response = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": result}}
    denial = check("mcp", "RESPONSE", response)
    if denial:
        # Mutations are already committed at this stage; output filtering is not rollback.
        raise ValueError(denial["body"]["error"]["data"]["reason_code"])
    return result


@mcp.tool(name="travel-discovery___search_hotels")
async def search_hotels(destination: str = "", gateway_capability: str = "") -> dict:
    return await dispatch("search_hotels", {"destination": destination}, gateway_capability)


@mcp.tool(name="travel-discovery___get_hotel_details")
async def get_hotel_details(hotel_id: str, gateway_capability: str = "") -> dict:
    return await dispatch("get_hotel_details", {"hotel_id": hotel_id}, gateway_capability)


@mcp.tool(name="travel-discovery___search_flights")
async def search_flights(destination: str = "Lisbon", gateway_capability: str = "") -> dict:
    return await dispatch("search_flights", {"destination": destination}, gateway_capability)


@mcp.tool(name="reservations___get_my_bookings")
async def get_my_bookings(booking_id: str = "", gateway_capability: str = "") -> dict:
    return await dispatch("get_my_bookings", {"booking_id": booking_id}, gateway_capability)


@mcp.tool(name="reservations___create_reservation")
async def create_reservation(quote_id: str, gateway_capability: str = "") -> dict:
    return await dispatch("create_reservation", {"quote_id": quote_id}, gateway_capability)


@mcp.tool(name="reservations___cancel_reservation")
async def cancel_reservation(booking_id: str, gateway_capability: str = "") -> dict:
    return await dispatch("cancel_reservation", {"booking_id": booking_id}, gateway_capability)


@mcp.tool(name="customer-payments___get_customer_profile")
async def get_customer_profile(gateway_capability: str = "") -> dict:
    return await dispatch("get_customer_profile", {}, gateway_capability)


@mcp.tool(name="customer-payments___list_customer_records")
async def list_customer_records(gateway_capability: str = "") -> dict:
    return await dispatch("list_customer_records", {}, gateway_capability)


@mcp.tool(name="customer-payments___process_mock_payment")
async def process_mock_payment(booking_id: str, gateway_capability: str = "") -> dict:
    return await dispatch("process_mock_payment", {"booking_id": booking_id}, gateway_capability)


@mcp.tool(name="customer-payments___issue_mock_refund")
async def issue_mock_refund(booking_id: str, gateway_capability: str = "") -> dict:
    return await dispatch("issue_mock_refund", {"booking_id": booking_id}, gateway_capability)


@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield


# Build the MCP app before lifespan uses its session manager.
mcp_app = mcp.streamable_http_app()
app = FastAPI(title="Offline AgentCore contract simulator", lifespan=lifespan)
app.mount("/tools", mcp_app)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "agentcore-offline",
        "real_aws": False,
        "inspection": "deterministic test markers only",
        "counters": counters.copy(),
    }


@app.post("/inference/v1/messages")
async def messages(request: Request):
    correlation = request.headers.get("X-Correlation-ID", "offline")[:80]
    raw = await request.body()
    if len(raw) > 65536:
        return JSONResponse({"reason_code": "PAYLOAD_TOO_LARGE"}, status_code=413)
    try:
        import json

        payload = json.loads(raw)
    except ValueError:
        return JSONResponse({"reason_code": "UNSUPPORTED_PAYLOAD"}, status_code=400)
    denial = check("http", "REQUEST", payload, correlation=correlation)
    if denial:
        return JSONResponse(decode(denial["body"]), status_code=denial["statusCode"])
    counters["inference_dispatches"] += 1
    last = payload["messages"][-1]["content"]
    if isinstance(last, list) and any(b.get("type") == "tool_result" for b in last):
        previous = payload["messages"][-2]["content"]
        tool = next(b["name"] for b in previous if b.get("type") == "tool_use")
        tool_result = next(b for b in last if b.get("type") == "tool_result")
        result = json.loads(tool_result["content"])["untrusted_tool_data"]
        content = [{"type": "text", "text": present(tool, result)["message"]}]
    else:
        text = last.lower() if isinstance(last, str) else ""
        if "offline-output-block-fixture" in text:
            content = [{"type": "text", "text": "AIGUARD_TEST_BLOCK_OUTPUT"}]
        elif "offline-identity-fixture" in text:
            content = [
                {
                    "type": "tool_use",
                    "id": "offline-tool-1",
                    "name": "issue_mock_refund",
                    "input": {"booking_id": "booking-alice", "role": "admin"},
                }
            ]
        else:
            call, reply = plan(text)
            content = (
                [
                    {
                        "type": "tool_use",
                        "id": "offline-tool-1",
                        "name": call.tool,
                        "input": call.arguments,
                    }
                ]
                if call
                else [{"type": "text", "text": reply}]
            )
    result = {
        "id": "offline-message",
        "type": "message",
        "role": "assistant",
        "model": "offline-fixture",
        "content": content,
        "stop_reason": "end_turn",
    }
    denial = check("http", "RESPONSE", result, correlation=correlation)
    if denial:
        return JSONResponse(decode(denial["body"]), status_code=denial["statusCode"])
    return result
