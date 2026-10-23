"""Verify signed ALB claims for the explicit AWS Trend lab, never plain identity headers."""

import hashlib
import math
import os
import re
import time

import httpx
import jwt
from fastapi import HTTPException

_cache = {}


def enabled():
    return os.getenv("APP_MODE") == "aws-demo" and os.getenv("ENABLE_AWS_TREND_GATEWAY") == "true"


def configuration():
    region = os.environ["AWS_REGION"]
    signer = os.environ["AWS_ALB_ARN"]
    issuer = os.environ["AWS_COGNITO_ISSUER"]
    client = os.environ["AWS_COGNITO_CLIENT_ID"]
    if not re.fullmatch(r"[a-z]{2}-[a-z]+-[0-9]", region):
        raise ValueError("Invalid cloud Region")
    if not re.fullmatch(
        rf"arn:aws:elasticloadbalancing:{region}:[0-9]{{12}}:loadbalancer/app/[a-z0-9-]+/[a-z0-9]+",
        signer,
    ):
        raise ValueError("Exact deployment ALB ARN is required")
    if not re.fullmatch(
        rf"https://cognito-idp\.{region}\.amazonaws\.com/{region}_[A-Za-z0-9]+", issuer
    ):
        raise ValueError("Exact deployment Cognito issuer is required")
    if not re.fullmatch(r"[a-z0-9]{1,128}", client):
        raise ValueError("Exact deployment client is required")
    return region, signer, issuer, client


def validate_claims(token, public_key, expected, now=None):
    region, signer, issuer, client = expected
    if not isinstance(token, str) or not 1 <= len(token) <= 16384:
        raise ValueError("Invalid token size")
    header = jwt.get_unverified_header(token)
    if (
        header.get("alg") != "ES256"
        or header.get("signer") != signer
        or header.get("iss") != issuer
        or header.get("client") != client
    ):
        raise ValueError("Untrusted ALB claims")
    expiry = float(header.get("exp", 0))
    current = time.time() if now is None else now
    if not math.isfinite(expiry) or not current < expiry <= current + 86400:
        raise ValueError("Expired or invalid ALB claims")
    body = jwt.decode(token, public_key, algorithms=["ES256"], options={"verify_aud": False})
    subject = body.get("sub")
    if not isinstance(subject, str) or not 1 <= len(subject) <= 256:
        raise ValueError("Missing operator subject")
    return hashlib.sha256((issuer + ":" + subject).encode()).hexdigest()[:32]


async def authenticate(request):
    try:
        expected = configuration()
        token = request.headers.get("x-amzn-oidc-data", "")
        if not 1 <= len(token) <= 16384:
            raise ValueError("Missing ALB claims")
        header = jwt.get_unverified_header(token)
        # Reject forged destination metadata before any network lookup.
        if (
            header.get("alg") != "ES256"
            or header.get("signer") != expected[1]
            or header.get("iss") != expected[2]
            or header.get("client") != expected[3]
        ):
            raise ValueError("Untrusted ALB metadata")
        kid = header.get("kid", "")
        if not isinstance(kid, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", kid):
            raise ValueError("Invalid key ID")
        cache_key = (expected[0], kid)
        now = time.monotonic()
        cached = _cache.get(cache_key)
        if not cached or cached[1] <= now:
            if len(_cache) >= 16:
                _cache.clear()
            async with httpx.AsyncClient(
                timeout=3, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.get(
                    f"https://public-keys.auth.elb.{expected[0]}.amazonaws.com/{kid}"
                )
                response.raise_for_status()
                if len(response.content) > 4096:
                    raise ValueError("Unexpected ALB signing key")
                key = response.text
            _cache[cache_key] = (key, now + 3600)
        else:
            key = cached[0]
        return validate_claims(token, key, expected)
    except (ValueError, KeyError, TypeError, jwt.PyJWTError, httpx.HTTPError):
        raise HTTPException(401, "Verified operator sign-in required") from None


def origin(request):
    if enabled():
        hostname = os.environ.get("AWS_APP_HOSTNAME", "")
        if (
            not re.fullmatch(r"boring-travel(?:-[a-z0-9]+)?(?:\.[a-z0-9-]+)+", hostname)
            or request.headers.get("host") != hostname
        ):
            raise ValueError("Unexpected deployment host")
        return "https://" + hostname
    return f"{request.url.scheme}://{request.headers.get('host')}"
