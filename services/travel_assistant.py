"""Read-only, deterministic travel assistant shared by local deployment profiles.

This is a scripted planner, not evidence that an LLM resisted prompt injection.
Tool descriptions and results never become executable planner instructions.
"""

import re

from services.contracts import Call

HELP = (
    "I can find stays in Lisbon, Kyoto, or Vancouver, share hotel details, "
    "and show your trips. Where would you like to go?"
)
READ_ONLY = (
    "I can help you explore stays and view your trips. "
    "Booking changes, payments, and refunds aren’t available in this chat."
)


# Friendly name matching for the fixed twelve-stay local inventory.
STAY_NAMES = (
    "Alfama House",
    "The Estuary",
    "Jardim Courtyard",
    "Azulejo Atelier",
    "Kamo River Lodge",
    "Higashiyama House",
    "The Moss Garden",
    "Lantern & Maple",
    "Coal Harbour Stay",
    "Cedar & Sea",
    "The Pacific Room",
    "North Shore House",
)


def plan(message):
    text = message.strip().lower()
    if not text:
        return None, HELP
    # Word boundaries avoid treating 'booking' as a request to book a stay.
    if re.search(r"\b(book|reserve|cancel|refund|pay|payment|approve|confirm)\b", text):
        return None, READ_ONLY
    hotel = re.search(r"\bh\d{2}\b", text)
    hotel_id = (
        hotel.group()
        if hotel
        else next(
            (f"h{index:02}" for index, name in enumerate(STAY_NAMES, 1) if name.lower() in text), ""
        )
    )
    if hotel_id:
        return Call(tool="get_hotel_details", arguments={"hotel_id": hotel_id}), ""
    if re.search(r"\b(bookings?|reservations?|trips?)\b", text):
        resource = re.search(r"\bbooking-[a-z0-9-]+\b", text)
        return Call(
            tool="get_my_bookings",
            arguments={"booking_id": resource.group() if resource else ""},
        ), ""
    city = next((c for c in ("Lisbon", "Kyoto", "Vancouver") if c.lower() in text), "")
    if city or re.search(r"\b(stays?|hotels?|destinations?|somewhere)\b", text):
        return Call(tool="search_hotels", arguments={"destination": city}), ""
    return None, HELP


def present(tool, response):
    """Only return allowlisted display fields; never echo tool prose or arguments."""
    if response.get("decision") != "ALLOW":
        return {
            "message": "I couldn’t access those details for your traveler profile. "
            "I can help you find stays or show your own trips instead.",
            "stays": [],
            "bookings": [],
        }
    data = response["result"]
    if tool in {"search_hotels", "get_hotel_details"}:
        rows = data.get("hotels", []) if tool == "search_hotels" else [data]
        stays = [
            {key: row[key] for key in ("id", "name", "destination", "price", "rating")}
            for row in rows
        ]
        if tool == "get_hotel_details":
            row = stays[0]
            message = (
                f"{row['name']} is in {row['destination']}, with a guest rating of "
                f"{row['rating']:.1f}/5. The listed rate is ${row['price'] / 100:.0f} USD "
                "per night. These are listed rates, not a live availability check."
            )
        else:
            cities = sorted({row["destination"] for row in stays})
            location = cities[0] if len(cities) == 1 else "our three destinations"
            message = (
                f"I found {len(stays)} stays in {location}. "
                "Take a look below, or choose a stay to find out more. Rates are in USD."
                if stays
                else "I couldn’t find a stay there. Try Lisbon, Kyoto, or Vancouver."
            )
        return {"message": message, "stays": stays, "bookings": []}
    if tool == "get_my_bookings":
        bookings = [
            {key: row[key] for key in ("hotel_name", "check_in", "check_out", "status")}
            for row in data.get("bookings", [])
        ]
        return {
            "message": "Here are your trips." if bookings else "You don’t have any trips yet.",
            "stays": [],
            "bookings": bookings,
        }
    return {"message": HELP, "stays": [], "bookings": []}


async def converse(message, login, correlation):
    from services.api import gateway_call

    call, reply = plan(message)
    if call is None:
        return {"message": reply, "model": "mock", "calls": [], "stays": [], "bookings": []}
    response = await gateway_call(login, call, correlation)
    return present(call.tool, response) | {
        "model": "mock",
        "calls": [
            {
                "tool": call.tool,
                "decision": response["decision"],
                "audit_id": response["audit_id"],
            }
        ],
    }
