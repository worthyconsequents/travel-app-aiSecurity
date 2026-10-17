import os
import time

from fastapi import HTTPException, Request

from services.db import Login, Session

IDENTITIES = {
    "alice": {"name": "Alice Chen", "agent": "travel-assistant", "role": "customer"},
    "bob": {"name": "Bob Rivera", "agent": "travel-assistant", "role": "customer"},
    "finance": {"name": "Finley · Finance", "agent": "finance-agent", "role": "finance"},
    "admin": {"name": "Morgan · Administrator", "agent": "admin-agent", "role": "administrator"},
}


def resolve(token):
    with Session() as db:
        login = db.get(Login, token or "")
        if not login or login.expires <= time.time() or login.human not in IDENTITIES:
            raise HTTPException(401, "Choose a local demo identity")
        if login.agent != IDENTITIES[login.human]["agent"]:
            raise HTTPException(401, "Invalid workload identity")
        return login


def session_cookie_name():
    return os.getenv("SESSION_COOKIE_NAME", "waypoint_session")


def current(request: Request):
    return resolve(request.cookies.get(session_cookie_name()))


def require_local():
    if os.getenv("APP_MODE", "local") != "local":
        raise RuntimeError(
            "Demo authentication is disabled outside APP_MODE=local; implement Cognito JWT validation before deployment"
        )
