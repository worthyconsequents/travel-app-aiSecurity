"""Independent operator authentication; never trusts customer demo identities."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from fastapi import HTTPException, Request

from services.auth import session_cookie_name


class PasswordProvider:
    def __init__(self, reader=None, clock=time.monotonic):
        self.reader, self.clock = reader, clock
        self.cached, self.expires = None, 0
        self.lock = threading.Lock()

    def password(self):
        source = os.getenv("MONITOR_PASSWORD_SOURCE", "env")
        if source == "env":
            value = os.getenv("MONITOR_PASSWORD", "")
        elif source == "aws":
            if os.getenv("ENABLE_AWS_MONITOR_SECRET") != "true":
                raise RuntimeError("AWS secret reads are not enabled")
            arn = os.getenv("MONITOR_SECRET_ARN", "")
            if not arn.startswith("arn:") or ":secretsmanager:" not in arn:
                raise RuntimeError("A Secrets Manager ARN is required")
            with self.lock:
                if self.cached and self.clock() < self.expires:
                    return self.cached
                if self.reader:
                    raw = self.reader(arn)
                else:
                    import boto3
                    from botocore.config import Config

                    client = boto3.client(
                        "secretsmanager",
                        region_name=os.getenv("AWS_REGION", "us-west-2"),
                        config=Config(
                            connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}
                        ),
                    )
                    raw = client.get_secret_value(SecretId=arn)["SecretString"]
                value = json.loads(raw)["password"]
                self.validate(value)
                self.cached, self.expires = value, self.clock() + 300
        else:
            raise RuntimeError("Unknown monitoring password source")
        self.validate(value)
        return value

    @staticmethod
    def validate(value):
        if not isinstance(value, str) or not 24 <= len(value) <= 256:
            raise RuntimeError("A monitoring password of 24–256 characters is required")


provider = PasswordProvider()


def password():
    try:
        return provider.password()
    except Exception:
        # Never return SDK errors, secret material, or credential provider details.
        raise HTTPException(503, "Monitoring authentication is unavailable") from None


def cookie_name():
    return session_cookie_name() + "_monitor"


def signing_key(value):
    return hmac.digest(value.encode(), cookie_name().encode(), "sha256")


def issue(value, now=None):
    expiry = int(time.time() if now is None else now) + 3600
    payload = f"{expiry}.{secrets.token_urlsafe(24)}"
    signature = hmac.new(signing_key(value), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{signature}".encode()).decode()


def valid(token, value, now=None):
    try:
        if len(token) > 256:
            return False
        raw = base64.b64decode(token, altchars=b"-_", validate=True).decode()
        expiry, nonce, signature = raw.split(".")
        current = time.time() if now is None else now
        if not current < int(expiry) <= current + 3600 or len(nonce) != 32:
            return False
        expected = hmac.new(
            signing_key(value), f"{expiry}.{nonce}".encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def require_monitor(request: Request):
    token = request.cookies.get(cookie_name(), "")
    if not token or not valid(token, password()):
        raise HTTPException(401, "Monitoring sign-in required")


class LoginLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock, self.attempts, self.lock = clock, {}, threading.Lock()

    def check(self, key):
        with self.lock:
            now = self.clock()
            self.attempts = {k: v for k, v in self.attempts.items() if v[1] > now}
            count, until = self.attempts.get(key, (0, now + 300))
            if count >= 5 or (key not in self.attempts and len(self.attempts) >= 1000):
                raise HTTPException(429, "Too many sign-in attempts. Try again in five minutes.")
            self.attempts[key] = (count + 1, until)

    def clear(self, key):
        with self.lock:
            self.attempts.pop(key, None)


limiter = LoginLimiter()
