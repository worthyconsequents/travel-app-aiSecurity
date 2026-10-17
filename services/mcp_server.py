import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from services.tool_runtime import execute

SERVICE = os.environ["SERVICE"]
mcp = FastMCP(
    SERVICE,
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost:*", "127.0.0.1:*", f"{SERVICE}:*"],
        allowed_origins=[],
    ),
)

if SERVICE == "travel-discovery":

    @mcp.tool()
    def search_hotels(destination: str = "", gateway_capability: str = "") -> dict:
        return execute("search_hotels", {"destination": destination}, gateway_capability)

    @mcp.tool()
    def get_hotel_details(hotel_id: str, gateway_capability: str = "") -> dict:
        return execute("get_hotel_details", {"hotel_id": hotel_id}, gateway_capability)

    @mcp.tool()
    def search_flights(destination: str = "Lisbon", gateway_capability: str = "") -> dict:
        return execute("search_flights", {"destination": destination}, gateway_capability)
elif SERVICE == "reservations":

    @mcp.tool()
    def get_my_bookings(booking_id: str = "", gateway_capability: str = "") -> dict:
        return execute("get_my_bookings", {"booking_id": booking_id}, gateway_capability)

    @mcp.tool()
    def create_reservation(quote_id: str, gateway_capability: str = "") -> dict:
        return execute("create_reservation", {"quote_id": quote_id}, gateway_capability)

    @mcp.tool()
    def cancel_reservation(booking_id: str, gateway_capability: str = "") -> dict:
        return execute("cancel_reservation", {"booking_id": booking_id}, gateway_capability)
elif SERVICE == "customer-payments":

    @mcp.tool()
    def get_customer_profile(gateway_capability: str = "") -> dict:
        return execute("get_customer_profile", {}, gateway_capability)

    @mcp.tool()
    def list_customer_records(gateway_capability: str = "") -> dict:
        return execute("list_customer_records", {}, gateway_capability)

    @mcp.tool()
    def process_mock_payment(booking_id: str, gateway_capability: str = "") -> dict:
        return execute("process_mock_payment", {"booking_id": booking_id}, gateway_capability)

    @mcp.tool()
    def issue_mock_refund(booking_id: str, gateway_capability: str = "") -> dict:
        return execute("issue_mock_refund", {"booking_id": booking_id}, gateway_capability)
else:
    raise RuntimeError("Unknown MCP service")


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok", "service": SERVICE, "transport": "streamable-http"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
