from sqlalchemy import select, update

from services.capability import verify
from services.contracts import MUTATIONS
from services.db import Approval, Booking, Hotel, Quote, Receipt, Session, record, uid


# Mutation and approval consumption share one database transaction. Conditional UPDATE
# serializes concurrent grant use; receipt lookup is scoped to the exact call fingerprint.
def execute(tool, args, grant):
    c = verify(grant, tool, args)
    with Session.begin() as db:
        if tool in MUTATIONS:
            approval = db.get(Approval, c["approval_ref"])
            prior = db.get(Receipt, c["receipt_key"])
            if prior:
                if prior.fingerprint != c["fingerprint"]:
                    raise ValueError("Idempotency scope mismatch")
                return prior.result
            import time

            if not approval or any(
                getattr(approval, k) != c[k] for k in ("human", "tool", "resource", "amount")
            ):
                raise ValueError("Approval scope mismatch")
            consumed = db.execute(
                update(Approval)
                .where(
                    Approval.id == approval.id,
                    Approval.used.is_(False),
                    Approval.expires > time.time(),
                )
                .values(used=True)
            )
            if consumed.rowcount != 1:
                raise ValueError("Approval expired or already consumed")
        human = c["human"]
        if tool == "search_hotels":
            city = args.get("destination", "")
            rows = db.scalars(
                select(Hotel).where(Hotel.destination.ilike(f"%{city}%")).order_by(Hotel.id)
            ).all()
            result = {"hotels": [record(x) for x in rows]}
        elif tool == "get_hotel_details":
            row = db.get(Hotel, args["hotel_id"])
            if not row:
                raise ValueError("Hotel not found")
            result = record(row)
        elif tool == "search_flights":
            result = {
                "flights": [
                    {
                        "id": "synthetic-flight-1",
                        "destination": args.get("destination", "Lisbon"),
                        "carrier": "Waypoint Air · synthetic",
                        "amount": 42000,
                    }
                ]
            }
        elif tool == "get_my_bookings":
            query = select(Booking).where(Booking.human == human)
            if args.get("booking_id"):
                query = query.where(Booking.id == args["booking_id"])
            result = {
                "bookings": [
                    record(b) | {"hotel_name": db.get(Hotel, b.hotel_id).name}
                    for b in db.scalars(query).all()
                ]
            }
        elif tool == "get_customer_profile":
            result = {
                "id": human,
                "name": "Alice Chen" if human == "alice" else "Bob Rivera",
                "payment_method": "Synthetic wallet",
            }
        elif tool == "create_reservation":
            q = db.get(Quote, args["quote_id"])
            if not q or q.human != human or q.expires <= time.time() or q.amount != c["amount"]:
                raise ValueError("Quote expired or invalid")
            b = Booking(
                id="booking-" + uid()[:12],
                human=human,
                hotel_id=q.hotel_id,
                check_in=q.check_in,
                check_out=q.check_out,
                guests=q.guests,
                amount=q.amount,
                status="confirmed",
                approval_id=c["approval_ref"],
            )
            db.add(b)
            result = {"booking_id": b.id, "status": "confirmed", "amount": b.amount}
        elif tool in {"cancel_reservation", "issue_mock_refund", "process_mock_payment"}:
            b = db.get(Booking, args["booking_id"])
            if not b or b.human != human or b.amount != c["amount"]:
                raise ValueError("Booking ownership or amount mismatch")
            if tool == "cancel_reservation":
                b.status = "cancelled"
            result = {"booking_id": b.id, "status": b.status, "mock": True, "operation": tool}
        else:
            raise ValueError("Tool cannot be dispatched")
        if tool in MUTATIONS:
            db.add(Receipt(key=c["receipt_key"], fingerprint=c["fingerprint"], result=result))
        return result
