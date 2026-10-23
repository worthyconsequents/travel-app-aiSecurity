"""Opaque, short-lived references preserve signed backend authorization."""

import hashlib
import math
import os
import re
import secrets
import time

from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from services.capability import verify


def reference_enabled():
    mode = os.getenv("TREND_CAPABILITY_TRANSPORT", "arguments")
    if mode not in {"arguments", "reference"}:
        raise RuntimeError("Unsupported capability transport")
    if mode == "arguments":
        return False
    if not (
        os.getenv("APP_MODE") == "aws-demo"
        and os.getenv("ENABLE_AWS_TREND_GATEWAY") == "true"
        and os.getenv("DEPLOYMENT_PROFILE") == "trend-gateway"
        and os.getenv("MODEL_MODE") == "mock"
    ):
        raise RuntimeError("Reference capabilities require explicit AWS Trend mock mode")
    return True


def cleanup():
    from services.db import CapabilityReference, Session

    try:
        with Session.begin() as db:
            db.execute(
                delete(CapabilityReference).where(CapabilityReference.expires <= time.time())
            )
    except SQLAlchemyError:
        raise RuntimeError("Capability reference storage unavailable") from None


def outgoing(arguments, tool):
    if not reference_enabled():
        return arguments
    from services.db import CapabilityReference, Session

    args = dict(arguments)
    token = args.pop("gateway_capability", "")
    if not isinstance(token, str) or len(token) > 16000:
        raise ValueError("Invalid capability transport value")
    claims = verify(token, tool, args)
    expiry = float(claims["expires"])
    if not math.isfinite(expiry) or not time.time() < expiry <= time.time() + 60:
        raise ValueError("Capability reference lifetime exceeds limit")
    reference = "btg_" + secrets.token_hex(16)
    try:
        with Session.begin() as db:
            db.execute(
                delete(CapabilityReference).where(CapabilityReference.expires <= time.time())
            )
            db.add(
                CapabilityReference(
                    id=hashlib.sha256(reference.encode()).hexdigest(), token=token, expires=expiry
                )
            )
    except SQLAlchemyError:
        raise RuntimeError("Capability reference storage unavailable") from None
    return args | {"gateway_capability": reference}


def incoming(argument):
    if not reference_enabled():
        return argument
    from services.db import CapabilityReference, Session

    if not isinstance(argument, str) or not re.fullmatch(r"btg_[a-f0-9]{32}", argument):
        raise ValueError("Missing, expired or invalid gateway capability")
    try:
        with Session() as db:
            row = db.get(CapabilityReference, hashlib.sha256(argument.encode()).hexdigest())
            if row is None or row.expires <= time.time():
                raise ValueError("Missing, expired or invalid gateway capability")
            return row.token
    except SQLAlchemyError:
        raise RuntimeError("Capability reference storage unavailable") from None
