"""Prepare ignored local configuration without displaying or replacing existing secrets."""

import json
import os
import secrets
from pathlib import Path


def main():
    private = Path("infra/trend-gateway/private")
    private.mkdir(parents=True, exist_ok=True)
    for name in ("tool-change-control-key", "travel-upstream-key"):
        path = private / name
        if not path.exists():
            with path.open("x", opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
                f.write(secrets.token_urlsafe(40) + "\n")
    path = private / "tool-changes.env"
    if not path.exists():
        values = {
            "PUBLIC_PORT": "8085",
            "MODEL_MODE": "mock",
            "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
            "MONITOR_PASSWORD": secrets.token_urlsafe(32),
            "TREND_LOCAL_UID": str(os.getuid()),
            "TREND_LOCAL_GID": str(os.getgid()),
            "TEST_DEPLOYMENT_ID": "dannytran-tool-changes-local",
            "TEST_SESSION_COOKIE_NAME": "boring_travel_tool_changes_session",
        }
        with path.open("x", opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
            f.write("".join(f"{k}={v}\n" for k, v in values.items()))
    mapping = Path("build/trend/tool-change-map.json")
    mapping.parent.mkdir(parents=True, exist_ok=True)
    if not mapping.exists():
        with mapping.open("x", opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
            f.write(json.dumps({}) + "\n")
    print("Private local configuration prepared; existing values preserved. No AWS operations.")


if __name__ == "__main__":
    main()
