from pydantic import BaseModel, ConfigDict, Field

TOOLS = {
    "search_hotels": "travel-discovery",
    "get_hotel_details": "travel-discovery",
    "search_flights": "travel-discovery",
    "get_my_bookings": "reservations",
    "create_reservation": "reservations",
    "cancel_reservation": "reservations",
    "get_customer_profile": "customer-payments",
    "list_customer_records": "customer-payments",
    "process_mock_payment": "customer-payments",
    "issue_mock_refund": "customer-payments",
}
MUTATIONS = {
    "create_reservation",
    "cancel_reservation",
    "process_mock_payment",
    "issue_mock_refund",
}
SPOOF = {
    "identity",
    "role",
    "approval_granted",
    "customer_id",
    "owner",
    "human",
    "agent",
    "_grant",
    "gateway_capability",
}


class Call(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict)
    approval_ref: str | None = Field(default=None, max_length=80)
    idempotency_key: str | None = Field(default=None, max_length=100)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hotel_id: str
    check_in: str
    check_out: str
    guests: int = Field(ge=1, le=6)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    resource: str


class LoginRequest(BaseModel):
    identity: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)


class GatewayAdapter:
    """A vendor adapter must return a policy decision before any downstream dispatch."""

    def evaluate(self, context: dict) -> dict:
        raise NotImplementedError
