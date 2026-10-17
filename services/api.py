import os
import time
from contextlib import asynccontextmanager
from datetime import date

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select

from services.agentcore.transport import deployment_profile
from services.auth import IDENTITIES, current, require_local, session_cookie_name
from services.contracts import TOOLS, ApprovalRequest, Call, ChatRequest, LoginRequest, Proposal
from services.db import Approval, Audit, Booking, Hotel, Login, Quote, Session, record, uid
from services.monitor import router as monitor_router
from services.seed import seed
from services.settings import require_runtime_configuration

require_local()
require_runtime_configuration()
deployment_profile()
GATEWAY = os.getenv("GATEWAY_URL", "http://gateway:8000")


@asynccontextmanager
async def lifespan(app):
    seed()
    yield


app = FastAPI(title="Waypoint · Local synthetic travel lab", lifespan=lifespan)
app.include_router(monitor_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    if request.url.path.startswith("/monitor"):
        return JSONResponse({"detail": "Invalid monitoring request"}, status_code=422)
    return await request_validation_exception_handler(request, exc)


@app.middleware("http")
async def boundaries(request: Request, call_next):
    if int(request.headers.get("content-length", "0")) > 65536:
        return Response(status_code=413)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return Response("Cross-origin request rejected", status_code=403)
    request.state.correlation_id = uid()
    response = await call_next(request)
    if request.url.path.startswith("/monitor"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    response.headers["X-Correlation-ID"] = request.state.correlation_id
    return response


@app.get("/health")
def health():
    with Session() as db:
        db.scalar(select(Hotel.id).limit(1))
    return {
        "status": "ok",
        "service": "agent-api",
        "model": os.getenv("MODEL_MODE", "mock"),
        "deployment_profile": deployment_profile(),
    }


@app.get("/identities")
def identities():
    return {"identities": [{"id": k, **v} for k, v in IDENTITIES.items()], "local_only": True}


@app.post("/session")
def login(body: LoginRequest, response: Response):
    if body.identity not in IDENTITIES:
        raise HTTPException(400, "Unknown demo identity")
    row = Login(
        id=uid() + uid(),
        human=body.identity,
        agent=IDENTITIES[body.identity]["agent"],
        expires=time.time() + 8 * 3600,
    )
    with Session.begin() as db:
        db.add(row)
    response.set_cookie(
        session_cookie_name(), row.id, httponly=True, samesite="strict", max_age=8 * 3600, path="/"
    )
    return {"id": row.human, **IDENTITIES[row.human]}


@app.get("/session")
def me(login=Depends(current)):
    return {"id": login.human, **IDENTITIES[login.human]}


async def gateway_call(login, call, correlation=None):
    cid = correlation or uid()
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(
                GATEWAY + "/invoke",
                headers={"Authorization": "Bearer " + login.id, "X-Correlation-ID": cid},
                json=call.model_dump(),
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        with Session.begin() as db:
            db.add(
                Audit(
                    id=uid(),
                    correlation_id=cid,
                    human=login.human,
                    agent=login.agent,
                    tool=call.tool,
                    server=TOOLS.get(call.tool, "unknown"),
                    resource="unresolved",
                    decision="DENY",
                    reason_code="ENFORCEMENT_UNAVAILABLE",
                    policy_id="fail-closed",
                    approval_state="unknown",
                    arguments={},
                    downstream=False,
                    outcome="not_dispatched",
                )
            )
        raise HTTPException(
            503,
            {"decision": "DENY", "reason_code": "ENFORCEMENT_UNAVAILABLE", "correlation_id": cid},
        )


@app.post("/tools/invoke")
async def invoke(body: Call, request: Request, login=Depends(current)):
    return await gateway_call(login, body, request.state.correlation_id)


@app.get("/hotels")
async def hotels(destination: str = "", login=Depends(current)):
    return await gateway_call(
        login, Call(tool="search_hotels", arguments={"destination": destination[:80]})
    )


@app.get("/hotels/{hotel_id}")
async def hotel(hotel_id: str, login=Depends(current)):
    return await gateway_call(
        login, Call(tool="get_hotel_details", arguments={"hotel_id": hotel_id})
    )


@app.get("/bookings")
async def bookings(login=Depends(current)):
    return await gateway_call(login, Call(tool="get_my_bookings", arguments={"booking_id": ""}))


@app.post("/quotes")
def quote(body: Proposal, login=Depends(current)):
    if login.human not in {"alice", "bob"}:
        raise HTTPException(403, "A customer identity is required")
    try:
        start, end = date.fromisoformat(body.check_in), date.fromisoformat(body.check_out)
        nights = (end - start).days
        if start < date.today() or not 1 <= nights <= 30:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "Choose future travel dates for a stay of 1–30 nights")
    with Session.begin() as db:
        hotel = db.get(Hotel, body.hotel_id)
        if not hotel:
            raise HTTPException(404, "Hotel not found")
        q = Quote(
            id=uid(),
            human=login.human,
            amount=hotel.price * nights,
            expires=time.time() + 600,
            **body.model_dump(),
        )
        db.add(q)
        return record(q) | {"hotel_name": hotel.name, "nights": nights, "currency": "USD"}


@app.post("/approvals")
def approve(body: ApprovalRequest, login=Depends(current)):
    with Session.begin() as db:
        resource = db.get(Quote if body.tool == "create_reservation" else Booking, body.resource)
        if body.tool not in {
            "create_reservation",
            "cancel_reservation",
            "process_mock_payment",
            "issue_mock_refund",
        }:
            raise HTTPException(400, "Unsupported approval scope")
        if not resource or resource.human != login.human:
            raise HTTPException(403, "Resource not owned by this identity")
        if body.tool == "create_reservation" and resource.expires <= time.time():
            raise HTTPException(409, "Quote expired")
        if body.tool == "issue_mock_refund" and login.agent != "finance-agent":
            raise HTTPException(403, "Finance workload required")
        grant = Approval(
            id=uid(),
            human=login.human,
            tool=body.tool,
            resource=body.resource,
            amount=resource.amount,
            expires=time.time() + 120,
            used=False,
        )
        db.add(grant)
        return record(grant)


@app.post("/chat")
async def chat(body: ChatRequest, request: Request, login=Depends(current)):
    from services.agent import converse
    from services.telemetry import emit

    cid = request.state.correlation_id
    emit(
        cid,
        "chat_received",
        login.human,
        login.agent,
        details={"profile": deployment_profile(), "model": os.getenv("MODEL_MODE", "mock")},
    )
    try:
        result = await converse(body.message, login, cid)
    except Exception:
        emit(cid, "chat_failed", login.human, login.agent, details={"outcome": "failed"})
        raise
    emit(
        cid,
        "chat_completed",
        login.human,
        login.agent,
        details={
            "model": result.get("model", "unknown"),
            "call_count": len(result.get("calls", [])),
        },
    )
    return result | {"traveler": login.human, "correlation_id": cid}


@app.get("/audit")
def events(request: Request, login=Depends(current)):
    if login.human == "admin":
        from services.monitor_auth import require_monitor

        require_monitor(request)
    with Session() as db:
        query = select(Audit)
        if login.human != "admin":
            query = query.where(Audit.human == login.human)
        rows = db.scalars(query.order_by(Audit.at.desc()).limit(200)).all()
        return {
            "events": [record(row) for row in rows],
            "gateway": "Local reference enforcement · vendor not configured",
        }


@app.post("/scenarios/run")
async def scenarios(request: Request, login=Depends(current)):
    if login.human != "admin":
        raise HTTPException(403, "Administrator demo identity required")
    from services.monitor_auth import require_monitor
    from services.scenarios import run_scenarios

    require_monitor(request)
    return await run_scenarios()
