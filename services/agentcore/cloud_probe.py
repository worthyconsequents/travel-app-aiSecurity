"""Read-only synthetic fixture for the isolated AWS staging gateway."""

import json
import re


def lambda_handler(event, context):
    custom = getattr(getattr(context, "client_context", None), "custom", {}) or {}
    name = custom.get("bedrockAgentCoreToolName", "")
    if not name.endswith("___get_test_hotel"):
        raise ValueError("Unknown staging tool")
    if (
        not isinstance(event, dict)
        or set(event) != {"query"}
        or not isinstance(event["query"], str)
        or not 1 <= len(event["query"]) <= 2000
    ):
        raise ValueError("Invalid staging arguments")
    request_id = str(getattr(context, "aws_request_id", "unavailable"))
    if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", request_id):
        request_id = "unavailable"
    print(json.dumps({"stage": "PROBE", "invocation_id": request_id}))
    return {
        "synthetic": True,
        "hotel_id": "cloud-test-h01",
        "name": "Sample Lisbon Stay",
        "city": "Lisbon",
        "read_only": True,
        "invocation_id": request_id,
    }
