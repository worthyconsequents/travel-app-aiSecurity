"""Verify the published NGINX boundary, including correct upstream identity and cookies."""

import json
import os
import urllib.request
from http.cookiejar import CookieJar

base = f"http://localhost:{os.getenv('PUBLIC_PORT', '8080')}"
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
for path, service in (("/health", "nginx"), ("/api/health", "agent-api")):
    with opener.open(base + path, timeout=10) as response:
        assert response.status == 200
        assert json.load(response)["service"] == service
        print(json.dumps({"path": path, "status": response.status, "service": service}))
with opener.open(base + "/", timeout=10) as response:
    assert response.status == 200 and b"boring-travel" in response.read()
request = urllib.request.Request(
    base + "/api/session",
    data=b'{"identity":"alice"}',
    headers={"Content-Type": "application/json", "Origin": base},
    method="POST",
)
with opener.open(request, timeout=10) as response:
    assert json.load(response)["id"] == "alice"
with opener.open(base + "/api/bookings", timeout=30) as response:
    result = json.load(response)
    assert result["decision"] == "ALLOW"
    assert all(b["human"] == "alice" for b in result["result"]["bookings"])
print(json.dumps({"proxy_session_and_owned_bookings": "passed"}))
