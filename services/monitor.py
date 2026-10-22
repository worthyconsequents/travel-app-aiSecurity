import asyncio
import hmac
import os
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from services import monitor_auth as auth
from services import test_jobs
from services.agentcore.transport import deployment_profile
from services.db import Activity, AttackRun, Audit, Session, record

router = APIRouter(prefix="/monitor", tags=["private monitoring"])
run_lock = asyncio.Lock()


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
async def login(body: Credentials, request: Request, response: Response):
    peer = request.client.host if request.client else "local"
    auth.limiter.check(peer)
    expected = await asyncio.to_thread(auth.password)
    if not hmac.compare_digest(body.password.encode(), expected.encode()):
        raise HTTPException(401, "Incorrect password")
    auth.limiter.clear(peer)
    response.set_cookie(
        auth.cookie_name(),
        auth.issue(expected),
        httponly=True,
        samesite="strict",
        secure=os.getenv("MONITOR_COOKIE_SECURE", "false") == "true",
        max_age=3600,
        path="/",
    )
    return {"authenticated": True}


@router.get("/session", dependencies=[Depends(auth.require_monitor)])
def session():
    return {"authenticated": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.cookie_name(), path="/")
    return {"authenticated": False}


@router.get("/data", dependencies=[Depends(auth.require_monitor)])
def data(limit: int = Query(default=100, ge=1, le=500)):
    with Session() as db:
        counts = dict(
            db.execute(select(Audit.decision, func.count()).group_by(Audit.decision)).all()
        )
        rows = db.scalars(select(Audit).order_by(Audit.at.desc(), Audit.id).limit(limit)).all()
        activity = db.scalars(select(Activity).order_by(Activity.at.desc()).limit(limit)).all()
        runs = db.scalars(select(AttackRun).order_by(AttackRun.started.desc()).limit(20)).all()
        return {
            "profile": deployment_profile(),
            "evidence": (
                "Application authorization and activity for this AWS copy. Inspector decisions "
                "are recorded separately in CloudWatch. Successful calls alone do not prove attack blocking."
                if deployment_profile() == "agentcore-aws"
                else "Application authorization through the local Trend MCP gateway. "
                "Vendor inspection decisions are recorded separately in Trend Events; "
                "an app denial alone does not establish a Trend detection."
                if deployment_profile() == "trend-gateway"
                else "Local reference enforcement; offline AgentCore interception where configured. "
                "Not live Trend detection or real-model susceptibility evidence."
            ),
            "model": os.getenv("MODEL_MODE", "mock"),
            "totals": counts,
            "audits": [record(row) for row in rows],
            "activity": [record(row) for row in activity],
            "runs": sorted(
                [record(row) for row in runs] + test_jobs.recent(Session),
                key=lambda row: row["started"],
                reverse=True,
            )[:20],
            "test_runner": test_jobs.capabilities(),
        }


@router.get("/flow/{correlation}", dependencies=[Depends(auth.require_monitor)])
def flow(correlation: str):
    if len(correlation) > 80:
        raise HTTPException(422, "Invalid correlation ID")
    with Session() as db:
        events = db.scalars(
            select(Activity)
            .where(Activity.correlation_id == correlation)
            .order_by(Activity.at, Activity.id)
            .limit(200)
        ).all()
        audits = db.scalars(
            select(Audit)
            .where(Audit.correlation_id == correlation)
            .order_by(Audit.at, Audit.id)
            .limit(100)
        ).all()
        if not events and not audits:
            raise HTTPException(404, "No recorded flow found")
        return {
            "correlation_id": correlation,
            "events": [record(event) for event in events],
            "audits": [record(row) for row in audits],
            "historical": not bool(events),
        }


@router.post("/runs", dependencies=[Depends(auth.require_monitor)])
async def run():
    if deployment_profile() not in {"local", "agentcore-offline"}:
        raise HTTPException(403, "This control runs local fixtures only")
    if os.getenv("TEST_RUNNER_ENABLED") == "true":
        raise HTTPException(409, "Use the durable monitoring test launcher")
    if run_lock.locked():
        raise HTTPException(409, "An attack test run is already in progress")
    from services.scenarios import run_scenarios

    async with run_lock:
        return await run_scenarios()


class TestLaunch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite: Literal["all", "connectivity", "authorization", "inspection", "tool-changes"] = "all"


@router.post("/test-runs", status_code=202, dependencies=[Depends(auth.require_monitor)])
def launch_test(
    body: TestLaunch,
    request: Request,
    idempotency_key: str = Header(pattern=r"^[a-zA-Z0-9-]{16,64}$"),
):
    if request.headers.get("X-Monitor-Action") != "run-tests":
        raise HTTPException(403, "Explicit monitoring action required")
    return test_jobs.enqueue(body.suite, idempotency_key)


@router.get("/test-runs/{job_id}", dependencies=[Depends(auth.require_monitor)])
def test_run(job_id: str):
    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        raise HTTPException(404, "Test run not found")
    return test_jobs.get(job_id)
