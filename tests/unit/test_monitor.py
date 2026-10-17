import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services import monitor, monitor_auth
from services.db import Activity, AttackRun, Audit, Base

PASSWORD = "unit-test-monitor-password-only-12345"


@pytest.fixture
def console(monkeypatch, tmp_path):
    from services.api import app

    engine = create_engine(
        f"sqlite:///{tmp_path}/monitor.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    db_session = sessionmaker(engine)
    monkeypatch.setattr(monitor, "Session", db_session)
    monkeypatch.setenv("MONITOR_PASSWORD", PASSWORD)
    monkeypatch.setenv("MONITOR_PASSWORD_SOURCE", "env")
    monkeypatch.setattr(monitor_auth, "limiter", monitor_auth.LoginLimiter())
    yield TestClient(app), db_session
    engine.dispose()


def sign_in(client):
    result = client.post("/monitor/login", json={"password": PASSWORD})
    assert result.status_code == 200
    return result


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/monitor/data"),
        ("GET", "/monitor/session"),
        ("GET", "/monitor/flow/abc"),
        ("POST", "/monitor/runs"),
    ],
)
def test_operator_data_is_password_locked(console, method, path):
    client, _ = console
    result = client.request(method, path)
    assert result.status_code == 401 and result.headers["cache-control"] == "no-store"


def test_customer_or_admin_identity_is_not_operator_auth(console, monkeypatch):
    client, _ = console
    from services.api import app
    from services.auth import current

    app.dependency_overrides[current] = lambda: SimpleNamespace(human="admin")
    try:
        assert client.get("/monitor/data").status_code == 401
        assert client.get("/audit").status_code == 401
        assert client.post("/scenarios/run").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_login_cookie_logout_and_no_secret_echo(console):
    client, _ = console
    response = sign_in(client)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert PASSWORD not in response.text and PASSWORD not in cookie
    assert client.get("/monitor/data").status_code == 200
    assert client.post("/monitor/logout").status_code == 200
    assert client.get("/monitor/data").status_code == 401


def test_bad_password_and_throttle(console):
    client, _ = console
    for _ in range(5):
        assert client.post("/monitor/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/monitor/login", json={"password": PASSWORD}).status_code == 429


def test_missing_password_and_provider_error_fail_closed(console, monkeypatch):
    client, _ = console
    monkeypatch.delenv("MONITOR_PASSWORD")
    result = client.post("/monitor/login", json={"password": "anything"})
    assert result.status_code == 503
    monkeypatch.setenv("MONITOR_PASSWORD_SOURCE", "aws")
    monkeypatch.delenv("ENABLE_AWS_MONITOR_SECRET", raising=False)
    assert client.post("/monitor/login", json={"password": "anything"}).status_code == 503


def test_tamper_expiry_rotation_and_profile_binding(monkeypatch):
    token = monitor_auth.issue(PASSWORD, now=100)
    assert monitor_auth.valid(token, PASSWORD, now=101)
    assert not monitor_auth.valid(token + "x", PASSWORD, now=101)
    assert not monitor_auth.valid(token, PASSWORD, now=3701)
    assert not monitor_auth.valid(token, PASSWORD + "rotated", now=101)
    monkeypatch.setenv("SESSION_COOKIE_NAME", "another-deployment")
    assert not monitor_auth.valid(token, PASSWORD, now=101)


def test_password_rotation_rejects_existing_cookie(console, monkeypatch):
    client, _ = console
    sign_in(client)
    monkeypatch.setenv("MONITOR_PASSWORD", PASSWORD + "rotated")
    assert client.get("/monitor/data").status_code == 401


def test_live_aws_reads_require_explicit_configuration_and_are_cached(monkeypatch):
    monkeypatch.setenv("MONITOR_PASSWORD_SOURCE", "aws")
    monkeypatch.setenv("ENABLE_AWS_MONITOR_SECRET", "true")
    monkeypatch.setenv(
        "MONITOR_SECRET_ARN", "arn:aws:secretsmanager:us-west-2:123456789012:secret:unit"
    )
    clock = Mock(return_value=0)
    reader = Mock(return_value=json.dumps({"password": PASSWORD}))
    provider = monitor_auth.PasswordProvider(reader, clock)
    assert provider.password() == provider.password() == PASSWORD
    reader.assert_called_once()
    clock.return_value = 301
    assert provider.password() == PASSWORD and reader.call_count == 2
    clock.return_value = 602
    reader.side_effect = RuntimeError("private-password-do-not-print")
    monkeypatch.setattr(monitor_auth, "provider", provider)
    with pytest.raises(HTTPException) as exc:
        monitor_auth.password()
    assert exc.value.status_code == 503 and "private-password" not in str(exc.value.detail)


def test_feed_and_flow_come_from_saved_records(console):
    client, sessions = console
    with sessions.begin() as db:
        db.add(
            Audit(
                id="audit-1",
                correlation_id="trace-1",
                human="alice",
                agent="travel-assistant",
                tool="get_my_bookings",
                server="reservations",
                resource="booking-bob",
                decision="DENY",
                reason_code="OWNERSHIP_MISMATCH",
                policy_id="reference-v1",
                approval_state="absent",
                arguments={"booking_id": "booking-bob"},
                downstream=False,
                outcome="not_dispatched",
            )
        )
        db.add(
            Activity(
                id="activity-1",
                correlation_id="trace-1",
                stage="policy_decision",
                human="alice",
                agent="travel-assistant",
                tool="get_my_bookings",
                audit_id="audit-1",
                details={"decision": "DENY"},
            )
        )
        db.add(AttackRun(id="run-1", profile="local", status="passed", result={"passed": True}))
    sign_in(client)
    data = client.get("/monitor/data").json()
    assert data["totals"] == {"DENY": 1}
    assert data["audits"][0]["id"] == "audit-1" and data["runs"][0]["id"] == "run-1"
    flow = client.get("/monitor/flow/trace-1").json()
    assert not flow["historical"] and flow["events"][0]["stage"] == "policy_decision"
    assert client.get("/monitor/flow/missing").status_code == 404
    assert client.get("/monitor/data?limit=501").status_code == 422


def test_telemetry_rejects_sensitive_extra_fields(monkeypatch, tmp_path):
    from services import telemetry

    engine = create_engine(f"sqlite:///{tmp_path}/activity.db")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(telemetry, "Session", sessions)
    telemetry.emit(
        "trace",
        "chat_received",
        "alice",
        "travel-assistant",
        details={
            "model": "mock",
            "password": PASSWORD,
            "message": "private user prompt",
            "token": "private",
        },
    )
    with sessions() as db:
        assert db.get(Activity, db.query(Activity).first().id).details == {"model": "mock"}
    engine.dispose()


def test_secret_deployment_plan_is_offline_and_apply_stores_exact_env_value(tmp_path):
    from scripts.deploy_monitor_secret import deploy

    env = tmp_path / ".env"
    env.write_text(f"MONITOR_PASSWORD={PASSWORD}\nAWS_REGION=us-west-2\n")
    client = Mock()
    plan = deploy(env, "generic/monitor", "us-west-2", client=client)
    client.create_secret.assert_not_called()
    assert PASSWORD not in str(plan)
    arn = "arn:aws:secretsmanager:us-west-2:123456789012:secret:unit"
    client.create_secret.return_value = {"ARN": arn}
    result = deploy(env, "generic/monitor", "us-west-2", apply=True, client=client)
    assert json.loads(client.create_secret.call_args.kwargs["SecretString"]) == {
        "password": PASSWORD
    }
    assert PASSWORD not in str(result)
    runtime = (tmp_path / "build/monitoring/runtime.env").read_text()
    assert PASSWORD not in runtime and arn in runtime
    assert env.stat().st_mode & 0o777 == 0o600


def test_validation_errors_do_not_echo_password(console):
    client, _ = console
    response = client.post("/monitor/login", json={"password": PASSWORD * 20})
    assert response.status_code == 422 and PASSWORD not in response.text
