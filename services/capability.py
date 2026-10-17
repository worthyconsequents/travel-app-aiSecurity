import base64
import hashlib
import hmac
import json
import os
import time

KEY = os.getenv("MCP_SIGNING_KEY", "local-reference-only-change-before-deployment").encode()


def fingerprint(tool, args):
    return hashlib.sha256(
        json.dumps([tool, args], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def sign(payload):
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
    return body + "." + hmac.new(KEY, body.encode(), hashlib.sha256).hexdigest()


def verify(token, tool, args):
    try:
        body, signature = token.split(".")
        expected = hmac.new(KEY, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(base64.urlsafe_b64decode(body))
        if payload["expires"] <= time.time() or payload["fingerprint"] != fingerprint(tool, args):
            raise ValueError("scope")
        return payload
    except Exception as exc:
        raise ValueError("Missing, expired or invalid gateway capability") from exc
