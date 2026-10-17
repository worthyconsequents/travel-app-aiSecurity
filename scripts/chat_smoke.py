"""Exercise real session/chat/gateway paths without model fees or booking mutations."""

import http.cookiejar
import json
import os
import urllib.error
import urllib.request

BASE = os.getenv("CHAT_BASE_URL", "http://localhost:8080")


def client():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def request(opener, path, body=None, base=None):
    req = urllib.request.Request(
        (base or BASE) + "/api" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with opener.open(req, timeout=45) as response:
        return json.load(response)


def run():
    anonymous = client()
    try:
        request(anonymous, "/chat", {"message": "Show my trips"})
        raise AssertionError("Anonymous chat was accepted")
    except urllib.error.HTTPError as error:
        assert error.code == 401
    alice, bob = client(), client()
    request(alice, "/session", {"identity": "alice"})
    request(bob, "/session", {"identity": "bob"})
    before = [request(c, "/bookings")["result"]["bookings"] for c in (alice, bob)]
    for city in ("Lisbon", "Kyoto", "Vancouver"):
        result = request(alice, "/chat", {"message": f"Find stays in {city}"})
        assert result["model"] == "mock" and result["traveler"] == "alice"
        assert len(result["stays"]) == 4 and all(s["destination"] == city for s in result["stays"])
        assert result["calls"][0]["tool"] == "search_hotels"
        assert result["calls"][0]["decision"] == "ALLOW"
    result = request(alice, "/chat", {"message": "Tell me about h04"})
    assert result["stays"][0]["name"] == "Azulejo Atelier"
    assert [c["tool"] for c in result["calls"]] == ["get_hotel_details"]
    assert "list_customer_records" not in json.dumps(result)
    for index, (c, who) in enumerate([(alice, "alice"), (bob, "bob")]):
        result = request(c, "/chat", {"message": "Show my trips"})
        assert result["traveler"] == who
        expected = [
            {key: row[key] for key in ("hotel_name", "check_in", "check_out", "status")}
            for row in before[index]
        ]
        assert result["bookings"] == expected
    denied = request(alice, "/chat", {"message": "Show booking-bob"})
    assert denied["calls"][0]["decision"] == "DENY" and denied["bookings"] == []
    audit = request(alice, "/audit")["events"]
    event = next(e for e in audit if e["id"] == denied["calls"][0]["audit_id"])
    assert event["reason_code"] == "OWNERSHIP_MISMATCH" and not event["downstream"]
    for text in ["Cancel booking-alice", "Book h01 for me", "Approve a refund"]:
        result = request(alice, "/chat", {"message": text})
        assert result["calls"] == []
    try:
        request(alice, "/chat", {"message": "  "})
        raise AssertionError("Blank message was accepted")
    except urllib.error.HTTPError as error:
        assert error.code == 422
    assert before == [request(c, "/bookings")["result"]["bookings"] for c in (alice, bob)]
    print(
        json.dumps(
            {
                "base_url": BASE,
                "passed": True,
                "checks": [
                    "authentication",
                    "three destinations",
                    "hotel injection fixture ignored",
                    "traveler isolation",
                    "cross-owner denial audited before dispatch",
                    "mutation requests make no tool calls",
                    "blank input rejected",
                    "no booking changes",
                ],
                "paid_model_calls": 0,
            },
            indent=2,
        )
    )


def parallel_sessions(other):
    shared = client()
    request(shared, "/session", {"identity": "alice"})
    request(shared, "/session", {"identity": "bob"}, base=other)
    assert request(shared, "/session")["id"] == "alice"
    assert request(shared, "/session", base=other)["id"] == "bob"
    assert request(shared, "/chat", {"message": "Show my trips"})["traveler"] == "alice"
    assert request(shared, "/chat", {"message": "Show my trips"}, base=other)["traveler"] == "bob"
    print(json.dumps({"parallel_deployment_sessions": "passed", "bases": [BASE, other]}))


if __name__ == "__main__":
    run()
    if other := os.getenv("CHAT_COMPARE_BASE_URL"):
        parallel_sessions(other)
