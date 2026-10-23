"""Private OpenAI-shaped adapter to bounded Bedrock Converse; no direct tool execution."""

import asyncio
import hmac
import json
import logging
import os
import re
import time
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Literal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

READ_TOOLS = {"search_hotels", "get_hotel_details", "get_my_bookings"}
PROVIDER_MODEL = "boring-travel-bedrock"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Function(Strict):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    arguments: str = Field(max_length=12000)


class ToolCall(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    type: Literal["function"] = "function"
    function: Function


class Message(Strict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = Field(default=None, max_length=12000)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=3)
    tool_call_id: str | None = Field(default=None, max_length=64)


class Definition(Strict):
    name: str
    description: str = Field(max_length=2000)
    parameters: dict


class Tool(Strict):
    type: Literal["function"] = "function"
    function: Definition


class Completion(Strict):
    model: Literal[PROVIDER_MODEL]
    messages: list[Message] = Field(min_length=1, max_length=20)
    tools: list[Tool] = Field(min_length=1, max_length=3)
    stream: Literal[False] = False
    max_tokens: int = Field(default=400, ge=1, le=1024)
    temperature: Literal[0] = 0


def deployment():
    namespace = os.getenv("TREND_K8S_NAMESPACE", "")
    if not (
        os.getenv("APP_MODE") == "aws-demo"
        and os.getenv("DEPLOYMENT_PROFILE") == "trend-gateway"
        and os.getenv("ENABLE_AWS_BEDROCK") == "true"
        and re.fullmatch(r"dannytran-boring-travel[a-z0-9-]{1,40}", namespace)
    ):
        raise RuntimeError("Bedrock adapter requires explicit AWS Trend deployment")
    model = os.getenv("BEDROCK_MODEL_ID", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.:-]{2,180}", model) or model.startswith(
        ("us.", "eu.", "apac.", "global.", "arn:")
    ):
        raise RuntimeError("Select one in-region foundation model; profiles are not supported yet")
    return model


@lru_cache(maxsize=4)
def bedrock_client(region):
    import boto3
    from botocore.config import Config

    return boto3.Session(region_name=region).client(
        "bedrock-runtime",
        config=Config(
            connect_timeout=3,
            read_timeout=35,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )


def reviewed_tools():
    baseline = json.loads(Path(__file__).with_name("approved_trend_catalog.json").read_text())
    result = {}
    for name in sorted(READ_TOOLS):
        schema = dict(baseline[name]["inputSchema"])
        schema["properties"] = {
            k: v for k, v in schema["properties"].items() if k != "gateway_capability"
        }
        schema["required"] = [k for k in schema.get("required", []) if k != "gateway_capability"]
        schema["additionalProperties"] = False
        result[name] = {"name": name, "description": name, "inputSchema": schema}
    return result


def translate(body, model):
    specs = {}
    reviewed = reviewed_tools()
    for item in body.tools:
        f = item.function
        if f.name not in READ_TOOLS or f.name in specs or len(json.dumps(f.parameters)) > 8000:
            raise ValueError("Unsupported tool definition")
        if f.parameters != reviewed[f.name]["inputSchema"] or f.description != f.name:
            raise ValueError("Tool contract differs from reviewed baseline")
        Draft202012Validator.check_schema(f.parameters)
        if f.parameters.get("type") != "object":
            raise ValueError("Object tool schema required")
        specs[f.name] = f
    messages, system, pending, seen = [], [], {}, set()
    previous_role = None
    for index, m in enumerate(body.messages):
        if m.role != "assistant" and m.tool_calls:
            raise ValueError("Unexpected tool calls")
        if m.role != "tool" and m.tool_call_id:
            raise ValueError("Unexpected tool result ID")
        if m.role == "system":
            if index != 0 or not m.content:
                raise ValueError("System message must be first")
            system = [{"text": m.content}]
        elif m.role == "tool":
            if m.tool_call_id not in pending or m.content is None:
                raise ValueError("Unmatched tool result")
            del pending[m.tool_call_id]
            block = {"toolResult": {"toolUseId": m.tool_call_id, "content": [{"text": m.content}]}}
            if previous_role == "tool":
                messages[-1]["content"].append(block)
            else:
                messages.append({"role": "user", "content": [block]})
        else:
            if pending:
                raise ValueError("Missing tool results")
            content = [{"text": m.content}] if m.content else []
            for call in m.tool_calls:
                f = call.function
                args = json.loads(f.arguments)
                if f.name not in specs or call.id in seen or not isinstance(args, dict):
                    raise ValueError("Invalid tool call")
                Draft202012Validator(specs[f.name].parameters).validate(args)
                seen.add(call.id)
                pending[call.id] = f.name
                content.append({"toolUse": {"toolUseId": call.id, "name": f.name, "input": args}})
            if not content:
                raise ValueError("Empty message")
            messages.append({"role": m.role, "content": content})
        previous_role = m.role
    if pending or not messages or messages[-1]["role"] != "user":
        raise ValueError("Complete user turn required")
    return {
        "modelId": model,
        "messages": messages,
        **({"system": system} if system else {}),
        "inferenceConfig": {"maxTokens": body.max_tokens, "temperature": 0},
        "toolConfig": {
            "tools": [
                {
                    "toolSpec": {
                        "name": f.name,
                        "description": f.description,
                        "inputSchema": {"json": f.parameters},
                    }
                }
                for f in specs.values()
            ]
        },
    }


def normalized(response, body):
    if response.get("stopReason") not in {"end_turn", "tool_use"}:
        raise ValueError("Incomplete model output")
    definitions = {t.function.name: t.function.parameters for t in body.tools}
    text, calls, ids = [], [], set()
    for b in response["output"]["message"]["content"]:
        if set(b) == {"text"} and isinstance(b["text"], str):
            text.append(b["text"])
        elif set(b) == {"toolUse"}:
            use = b["toolUse"]
            name, ident, args = use["name"], use["toolUseId"], use["input"]
            if (
                name not in definitions
                or ident in ids
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", ident)
                or not isinstance(args, dict)
            ):
                raise ValueError("Unapproved model tool output")
            Draft202012Validator(definitions[name]).validate(args)
            ids.add(ident)
            calls.append(
                {
                    "id": ident,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            )
        else:
            raise ValueError("Unsupported model content")
    if len(calls) > 3 or (response["stopReason"] == "tool_use") != bool(calls):
        raise ValueError("Invalid model stop reason")
    content = " ".join(text)
    if len(content) > 8000 or (not content and not calls):
        raise ValueError("Invalid model output size")
    usage = response.get("usage", {})
    counts = {k: usage.get(k, 0) for k in ("inputTokens", "outputTokens")}
    if any(type(v) is not int or not 0 <= v <= 1000000 for v in counts.values()):
        raise ValueError("Invalid token accounting")
    return {
        "id": "bedrock-" + str(time.time_ns()),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": PROVIDER_MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls" if calls else "stop",
                "message": {
                    "role": "assistant",
                    "content": content or None,
                    **({"tool_calls": calls} if calls else {}),
                },
            }
        ],
        "usage": {
            "prompt_tokens": counts["inputTokens"],
            "completion_tokens": counts["outputTokens"],
            "total_tokens": sum(counts.values()),
        },
    }


def create_app():
    model = deployment()
    from fastapi.exceptions import RequestValidationError

    app = FastAPI(title="Private boring-travel Bedrock adapter")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": "Unsupported model request"}, status_code=422)

    app.state.calls = deque()
    app.state.lock = asyncio.Lock()

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if request.url.path != "/health":
            try:
                key = Path(os.environ["BEDROCK_PROVIDER_KEY_FILE"]).read_text().strip()
            except (KeyError, OSError):
                return JSONResponse({"detail": "Provider credential unavailable"}, 503)
            if len(key) < 24 or not hmac.compare_digest(
                request.headers.get("Authorization", ""), "Bearer " + key
            ):
                return JSONResponse({"detail": "Unauthorized"}, 401)
            if len(await request.body()) > 65536:
                return JSONResponse({"detail": "Request too large"}, 413)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok", "inference_enabled": os.getenv("ENABLE_PAID_INFERENCE") == "true"}

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": PROVIDER_MODEL, "object": "model"}]}

    @app.post("/v1/chat/completions")
    async def completion(body: Completion):
        if os.getenv("ENABLE_PAID_INFERENCE") != "true":
            raise HTTPException(403, "Paid inference is disabled")
        from jsonschema.exceptions import SchemaError, ValidationError

        try:
            payload = translate(body, model)
        except (ValueError, TypeError, SchemaError, ValidationError):
            raise HTTPException(422, "Unsupported model request") from None
        # One process/replica and no SDK retries; hourly request bound survives only this process.
        if app.state.lock.locked():
            raise HTTPException(429, "Model adapter is busy")
        async with app.state.lock:
            now = time.monotonic()
            while app.state.calls and app.state.calls[0] <= now - 3600:
                app.state.calls.popleft()
            limit = int(os.getenv("BEDROCK_MAX_REQUESTS_PER_HOUR", "60"))
            if not 1 <= limit <= 1000 or len(app.state.calls) >= limit:
                raise HTTPException(429, "Model request allowance exhausted")
            app.state.calls.append(now)
            try:
                response = await asyncio.to_thread(
                    bedrock_client(os.environ["AWS_REGION"]).converse, **payload
                )
                result = normalized(response, body)
            except (BotoCoreError, ClientError, ValueError, KeyError, TypeError, ValidationError):
                raise HTTPException(502, "Bedrock request failed; no fallback used") from None
        # Numeric accounting only. Never log prompts, tool output, auth headers or provider errors.
        logging.getLogger(__name__).info(
            "bedrock_usage input=%d output=%d",
            result["usage"]["prompt_tokens"],
            result["usage"]["completion_tokens"],
        )
        return result

    return app
