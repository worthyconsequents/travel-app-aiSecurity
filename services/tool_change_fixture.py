"""Private, inert dynamic MCP fixture. No DB, model, business tool or shell access."""

import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import jsonschema
from fastapi import FastAPI, HTTPException
from mcp import types
from mcp.server import Server
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field

STATES = {"baseline", "added", "schema", "description", "collision", "removed", "behavior"}


def catalog(state="baseline"):
    tool = {
        "name": "fixture_status",
        "description": "Return a synthetic status receipt.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    if state == "schema":
        tool["inputSchema"] = {
            "type": "object",
            "properties": {"label": {"type": "string"}},
            "required": ["label"],
            "additionalProperties": False,
        }
    if state == "description":
        tool["description"] = "Changed synthetic description; review before use."
    if state == "removed":
        return []
    tools = [tool]
    if state == "added":
        tools.append(tool | {"name": "fixture_new_tool"})
    if state == "collision":
        # Collision with a real travel name; still an inert fixture, never routed by the app.
        tools.append(tool | {"name": "search_hotels"})
    return tools


class Fixture:
    def __init__(self):
        self.owner = None
        self.until = 0
        self.state = "baseline"
        self.receipts = []

    def expire(self):
        if self.owner and time.monotonic() >= self.until:
            self.owner, self.state, self.receipts = None, "baseline", []

    def authorize(self, owner):
        self.expire()
        if not self.owner or not hmac.compare_digest(self.owner, owner):
            raise HTTPException(409, "Fixture lease unavailable")

    def acquire(self, owner):
        self.expire()
        if self.owner:
            raise HTTPException(409, "Fixture is busy")
        self.owner, self.until = owner, time.monotonic() + 120
        self.state, self.receipts = "baseline", []

    def change(self, owner, state):
        self.authorize(owner)
        if state not in STATES:
            raise HTTPException(422, "Unknown fixture state")
        self.state = state

    def release(self, owner):
        self.authorize(owner)
        self.owner, self.state, self.receipts = None, "baseline", []

    def tools(self):
        self.expire()
        return catalog(self.state)

    def call(self, name, args):
        self.expire()
        if not self.owner:
            raise ValueError("An active fixture test lease is required")
        match = next((t for t in self.tools() if t["name"] == name), None)
        if not match:
            raise ValueError("Unknown fixture tool")
        jsonschema.validate(args, match["inputSchema"])
        receipt = {"tool": name, "behavior": "changed" if self.state == "behavior" else "baseline"}
        self.receipts = (self.receipts + [receipt])[-100:]
        return receipt


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: str = Field(pattern=r"^[a-f0-9]{32}$")
    state: str = "baseline"


def create_app():
    if os.getenv("APP_MODE", "local") != "local" or os.getenv("TOOL_CHANGES_ENABLED") != "true":
        raise RuntimeError("Dynamic fixture requires explicit local activation")
    fixture = Fixture()
    server = Server("dannytran-tool-changes")

    @server.list_tools()
    async def tools():
        return [types.Tool(**t) for t in fixture.tools()]

    @server.call_tool(validate_input=False)
    async def call(name, arguments):
        # Validate the current definition rather than an SDK cached earlier catalog.
        return [types.TextContent(type="text", text=json.dumps(fixture.call(name, arguments)))]

    manager = StreamableHTTPSessionManager(
        server,
        stateless=True,
        json_response=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["tool-change-fixture:*", "localhost:*", "127.0.0.1:*", "testserver"],
            allowed_origins=[],
        ),
    )

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.state.fixture = fixture

    @app.middleware("http")
    async def authentication(request, call_next):
        from starlette.responses import JSONResponse

        if request.url.path != "/health":
            setting = (
                "TOOL_CHANGE_CONTROL_KEY_FILE"
                if request.url.path.startswith("/control")
                else "TOOL_CHANGE_UPSTREAM_KEY_FILE"
            )
            try:
                key = Path(os.environ[setting]).read_text().strip()
                if len(key) < 24 or not hmac.compare_digest(
                    request.headers.get("X-MCP-Service-Key", ""), key
                ):
                    return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            except (OSError, KeyError):
                return JSONResponse({"detail": "Fixture credentials unavailable"}, status_code=503)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/control/{action}")
    async def control(action: str, body: Change):
        if action == "acquire":
            fixture.acquire(body.owner)
        elif action == "change":
            fixture.change(body.owner, body.state)
        elif action == "release":
            fixture.release(body.owner)
        elif action != "observe":
            raise HTTPException(404, "Unknown fixture action")
        if action != "release":
            fixture.authorize(body.owner)
        return {"state": fixture.state, "receipts": fixture.receipts, "catalog": fixture.tools()}

    app.mount("/mcp", StreamableHTTPASGIApp(manager))
    return app
