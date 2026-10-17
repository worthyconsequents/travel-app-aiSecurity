"""Structured activity only: no raw chat, passwords, tokens, or tool output."""

from services.db import Activity, Session, uid


def emit(correlation_id, stage, human, agent, tool="", audit_id="", details=None):
    permitted = {"decision", "reason_code", "outcome", "profile", "model", "call_count"}
    safe = {k: v for k, v in (details or {}).items() if k in permitted}
    with Session.begin() as db:
        db.add(
            Activity(
                id=uid(),
                correlation_id=correlation_id[:80],
                stage=stage,
                human=human,
                agent=agent,
                tool=tool,
                audit_id=audit_id,
                details=safe,
            )
        )
