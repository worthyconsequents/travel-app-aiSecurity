"""Inert local OpenAI-shaped provider. No SDK, inference, callbacks or outbound HTTP."""

import hmac
import os
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from services.tool_change_fixture import catalog

MODEL = "dannytran-mock-model"


class Function(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["fixture_status", "fixture_new_tool"]
    description: str = Field(max_length=200)
    parameters: dict


class Tool(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["function"]
    function: Function


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user"]
    content: Literal["Local synthetic inventory probe."]


class Completion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Literal[MODEL]
    messages: list[Message] = Field(min_length=1, max_length=1)
    tools: list[Tool] = Field(min_length=1, max_length=2)
    stream: Literal[False] = False
    max_tokens: int = Field(default=32, ge=1, le=64)
    temperature: Literal[0] = 0


def create_app():
    from services.fixture_scope import allowed_mode

    if not allowed_mode() or os.getenv("MODEL_PROBE_ENABLED") != "true":
        raise RuntimeError("Mock provider requires explicit isolated fixture activation")
    app = FastAPI()
    app.state.receipts = []

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if request.url.path != "/health":
            try:
                key = Path(os.environ["MODEL_PROBE_KEY_FILE"]).read_text().strip()
                if len(key) < 24 or not hmac.compare_digest(
                    request.headers.get("Authorization", ""), "Bearer " + key
                ):
                    return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            except (OSError, KeyError):
                return JSONResponse({"detail": "Mock credential unavailable"}, status_code=503)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok", "provider": "inert-local-mock"}

    @app.get("/v1/models")
    def models():
        return {
            "object": "list",
            "data": [{"id": MODEL, "object": "model", "owned_by": "local-fixture"}],
        }

    @app.get("/probe-receipts")
    def receipts():
        return {"calls": app.state.receipts, "paid_model_calls": 0}

    @app.post("/v1/chat/completions")
    def completion(body: Completion):
        baseline = {t["name"]: t for t in catalog("added")}
        names = [t.function.name for t in body.tools]
        if len(set(names)) != len(names):
            raise HTTPException(422, "Duplicate fixture tool")
        for tool in body.tools:
            expected = baseline[tool.function.name]
            if (
                tool.function.description != expected["description"]
                or tool.function.parameters != expected["inputSchema"]
            ):
                raise HTTPException(422, "Only the fixed synthetic tool definitions are accepted")
        selected = "fixture_new_tool" if "fixture_new_tool" in names else "fixture_status"
        receipt = {"at": time.time(), "model": MODEL, "tools": names, "selected": selected}
        app.state.receipts = (app.state.receipts + [receipt])[-50:]
        return {
            "id": "chatcmpl-local-fixture",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_local_fixture",
                                "type": "function",
                                "function": {"name": selected, "arguments": "{}"},
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    return app
