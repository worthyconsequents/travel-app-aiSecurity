import time

from services.contracts import SPOOF, TOOLS, GatewayAdapter

DISCOVERY = {"search_hotels", "get_hotel_details", "search_flights"}


def has_spoof(value):
    if isinstance(value, dict):
        return any(k.lower() in SPOOF or has_spoof(v) for k, v in value.items())
    if isinstance(value, list):
        return any(has_spoof(v) for v in value)
    return False


class ReferenceGateway(GatewayAdapter):
    def evaluate(self, c):
        def result(decision, reason):
            return {
                "decision": decision,
                "reason_code": reason,
                "policy_id": "reference-v1",
                "audit_id": c["audit_id"],
            }

        tool, human, agent = c["tool"], c["human"], c["agent"]
        if has_spoof(c["arguments"]):
            return result("DENY", "IDENTITY_ASSERTION_REJECTED")
        if tool not in TOOLS:
            return result("DENY", "UNKNOWN_TOOL")
        if human not in {"alice", "bob", "finance", "admin"} or agent not in {
            "travel-assistant",
            "finance-agent",
            "admin-agent",
        }:
            return result("DENY", "UNKNOWN_IDENTITY")
        if c["arguments"].get("destination_url"):
            return result("DENY", "UNAPPROVED_DESTINATION")
        if tool in DISCOVERY:
            return (
                result("ALLOW", "DISCOVERY_ALLOWED")
                if agent == "travel-assistant"
                else result("DENY", "WORKLOAD_NOT_ALLOWED")
            )
        if tool == "list_customer_records":
            return result("DENY", "BULK_DATA_DENIED")
        if tool == "issue_mock_refund" and agent != "finance-agent":
            return result("DENY", "FINANCE_AGENT_REQUIRED")
        if tool != "issue_mock_refund" and agent != "travel-assistant":
            return result("DENY", "WORKLOAD_NOT_ALLOWED")
        if c["owner"] != human:
            return result("DENY", "OWNERSHIP_MISMATCH")
        if not c.get("resource_valid", True):
            return result("DENY", "RESOURCE_INVALID")
        if tool in {"get_my_bookings", "get_customer_profile"}:
            return result("ALLOW", "OWNER_READ_ALLOWED")
        approval = c.get("approval")
        if not approval:
            return result("REQUIRE_APPROVAL", "EXPLICIT_APPROVAL_REQUIRED")
        if approval["used"] or approval["expires"] <= time.time():
            return result("DENY", "APPROVAL_EXPIRED_OR_USED")
        if any(approval[k] != c[k] for k in ("human", "tool", "resource", "amount")):
            return result("DENY", "APPROVAL_SCOPE_MISMATCH")
        return result("ALLOW", "SCOPED_APPROVAL_VALID")
