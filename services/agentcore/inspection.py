"""Content inspection clients. The offline client is a fixture, not a detector."""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Verdict:
    action: str
    reason_count: int = 0


class OfflineInspector:
    """Only reserved test markers trigger blocks. Makes no network calls."""

    def inspect(self, text):
        if "AIGUARD_TEST_UNAVAILABLE" in text:
            raise RuntimeError("Offline inspection outage fixture")
        return Verdict("block" if "AIGUARD_TEST_BLOCK" in text else "allow")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError("Inspection redirects are disabled")


class AIGuardInspector:
    HOSTS = {
        "api.xdr.trendmicro.com",
        "api.eu.xdr.trendmicro.com",
        "api.au.xdr.trendmicro.com",
        "api.jp.xdr.trendmicro.com",
        "api.sg.xdr.trendmicro.com",
        "api.in.xdr.trendmicro.com",
    }

    def __init__(self, endpoint, secret_arn, application, secret_reader=None, clock=time.monotonic):
        url = urlsplit(endpoint)
        if (
            url.scheme != "https"
            or url.hostname not in self.HOSTS
            or url.path != "/v3.0/aiSecurity/applyGuardrails"
            or url.query
            or url.fragment
            or url.username
            or url.password
            or url.port not in (None, 443)
        ):
            raise ValueError("Unsupported AI Guard regional endpoint")
        if not secret_arn or not application or len(application) > 100:
            raise ValueError("Secret ARN and application name are required")
        self.endpoint, self.secret_arn, self.application = endpoint, secret_arn, application
        self.secret_reader = secret_reader
        self.clock = clock
        self.cached = None
        self.expires = 0
        self.lock = threading.Lock()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def token(self):
        with self.lock:
            if self.cached and self.clock() < self.expires:
                return self.cached
            if self.secret_reader is None:
                import boto3
                from botocore.config import Config

                client = boto3.client(
                    "secretsmanager",
                    config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}),
                )
                value = client.get_secret_value(SecretId=self.secret_arn)["SecretString"]
            else:
                value = self.secret_reader(self.secret_arn)
            try:
                parsed = json.loads(value)
                value = next(parsed[k] for k in ("token", "apiKey", "api_key") if k in parsed)
            except json.JSONDecodeError:
                pass
            if not isinstance(value, str) or not value or any(c.isspace() for c in value):
                raise ValueError("Invalid secret format")
            self.cached, self.expires = value, self.clock() + 300
            return value

    def inspect(self, text):
        payload = json.dumps({"prompt": text}).encode()
        for attempt in range(2):
            request = urllib.request.Request(
                self.endpoint,
                data=payload,
                method="POST",
                headers={
                    "Authorization": "Bearer " + self.token(),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Prefer": "return=representation",
                    "TMV1-Application-Name": self.application,
                },
            )
            try:
                with self.opener.open(request, timeout=3) as response:
                    raw = response.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Oversized inspection response")
                result = json.loads(raw)
                action = str(result.get("action", "")).lower()
                if action not in {"allow", "block"}:
                    raise ValueError("Unknown inspection action")
                reasons = result.get("reasons", [])
                if not isinstance(reasons, list):
                    raise ValueError("Invalid inspection reasons")
                return Verdict(action, len(reasons))
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and attempt == 0:
                    self.cached, self.expires = None, 0
                    continue
                raise RuntimeError("AI Guard inspection failed") from None
        raise RuntimeError("AI Guard inspection failed")


def configured_inspector():
    # Offline mode requires explicit selection; it cannot become a cloud fallback.
    mode = os.getenv("AI_GUARD_MODE", "real")
    if mode == "offline":
        if os.getenv("APP_MODE") != "local":
            raise RuntimeError("Offline inspection is local-only")
        return OfflineInspector()
    if mode != "real":
        raise ValueError("Unknown inspection mode")
    return AIGuardInspector(
        os.environ["AI_GUARD_URL"],
        os.environ["AI_GUARD_SECRET_ARN"],
        os.environ["AI_GUARD_APPLICATION_NAME"],
    )
