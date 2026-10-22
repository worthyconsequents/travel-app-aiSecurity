import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services import monitor, monitor_auth
from services import test_cases as cases
from services import test_jobs as jobs
from services import test_worker as worker
from services.db import Base
from services.db import TestJob as Job
from services.db import TestJobLock as JobLock

PASSWORD = "test-runner-operator-password-only-1234"
HEADERS = {"X-Monitor-Action": "run-tests", "Idempotency-Key": "request-key-123456789"}


@pytest.fixture
def runner(monkeypatch, tmp_path):
    from services.api import app

    engine = create_engine(
        f"sqlite:///{tmp_path}/runner.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    for mod in [jobs, monitor, cases]:
        monkeypatch.setattr(mod, "Session", sessions)
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("MODEL_MODE", "mock")
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("TEST_DEPLOYMENT_ID", "unit-copy-one")
    monkeypatch.setenv("TEST_RUNNER_ENABLED", "true")
    monkeypatch.setenv("TEST_RUNNER_BACKEND", "local-worker")
    monkeypatch.setenv("MONITOR_PASSWORD", PASSWORD)
    monkeypatch.setenv("MONITOR_PASSWORD_SOURCE", "env")
    monkeypatch.setattr(monitor_auth, "limiter", monitor_auth.LoginLimiter())
    client = TestClient(app)
    jobs.presence()
    yield client, sessions
    engine.dispose()


def login(client):
    assert client.post("/monitor/login", json={"password": PASSWORD}).status_code == 200


def launch(client, suite="all", headers=None):
    return client.post("/monitor/test-runs", json={"suite": suite}, headers=headers or HEADERS)


@pytest.mark.parametrize(
    "method,path", [("POST", "/monitor/test-runs"), ("GET", "/monitor/test-runs/" + "a" * 32)]
)
def test_run_endpoints_require_operator(runner, method, path):
    c, _ = runner
    assert c.request(method, path, json={"suite": "all"}, headers=HEADERS).status_code == 401


def test_accepted_run_is_durable_and_idempotent(runner):
    c, s = runner
    login(c)
    first = launch(c)
    assert first.status_code == 202 and first.json()["status"] == "queued"
    assert launch(c).json()["id"] == first.json()["id"]
    assert c.get("/monitor/test-runs/" + first.json()["id"]).json()["status"] == "queued"
    feed = c.get("/monitor/data").json()
    assert feed["test_runner"]["ready"] and feed["runs"][0]["id"] == first.json()["id"]
    assert not any(k in first.json() for k in ["owner", "deadline", "scope", "heartbeat"])


@pytest.mark.parametrize(
    "body",
    [
        {"suite": "shell"},
        {"suite": "all", "command": "echo secret"},
        {"suite": "inspection", "url": "https://untrusted.invalid"},
    ],
)
def test_only_allowlisted_suite_without_extra_arguments(runner, body):
    c, _ = runner
    login(c)
    assert c.post("/monitor/test-runs", json=body, headers=HEADERS).status_code == 422


def test_action_header_origin_and_request_key_required(runner):
    c, _ = runner
    login(c)
    assert launch(c, headers={"Idempotency-Key": HEADERS["Idempotency-Key"]}).status_code == 403
    assert launch(c, headers=HEADERS | {"Origin": "https://untrusted.invalid"}).status_code == 403
    assert launch(c, headers={"X-Monitor-Action": "run-tests"}).status_code == 422


@pytest.mark.parametrize(
    "setting,value",
    [
        ("APP_MODE", "aws-demo"),
        ("MODEL_MODE", "agentcore"),
        ("TEST_RUNNER_ENABLED", "false"),
        ("TEST_RUNNER_BACKEND", "ecs"),
    ],
)
def test_cloud_paid_and_disabled_modes_cannot_dispatch(runner, monkeypatch, setting, value):
    c, _ = runner
    login(c)
    monkeypatch.setenv(setting, value)
    assert launch(c).status_code == 403


def test_stopped_worker_cannot_accept_new_run(runner):
    c, s = runner
    login(c)
    from services.db import TestWorkerPresence as Presence

    with s.begin() as db:
        db.get(Presence, jobs.scope()).at = time.time() - 60
    assert launch(c).status_code == 503
    assert not c.get("/monitor/data").json()["test_runner"]["ready"]


def test_concurrent_launches_have_one_scope_lock(runner):
    _, s = runner

    def enqueue(key):
        try:
            return jobs.enqueue("all", key)["id"]
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(enqueue, ["a" * 20, "b" * 20]))
    assert sum(isinstance(r, str) for r in results) == 1 and 409 in results
    with s() as db:
        assert db.query(Job).count() == 1 and db.query(JobLock).count() == 1


def test_identical_concurrent_requests_replay_same_job(runner):
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: jobs.enqueue("all", "same-request-key-1234"), range(2)))
    assert rows[0]["id"] == rows[1]["id"]


def test_only_one_worker_claims_and_wrong_owner_cannot_store(runner):
    j = jobs.enqueue("all", "request-claim-123456")
    assert jobs.claim("worker-a") == j["id"]
    assert jobs.claim("worker-b") is None
    with pytest.raises(RuntimeError):
        jobs.store(j["id"], "worker-b", {})
    jobs.store(j["id"], "worker-a", {"scenarios": []}, "passed")
    assert jobs.get(j["id"])["status"] == "passed"
    assert jobs.enqueue("all", "next-request-key-1234")["id"] != j["id"]


def test_expiry_keeps_partial_results_and_fences_old_worker(runner):
    _, s = runner
    j = jobs.enqueue("all", "expiry-request-1234")
    jobs.claim("old")
    jobs.store(j["id"], "old", {"scenarios": [{"id": 1, "status": "passed"}]})
    with s.begin() as db:
        db.get(Job, j["id"]).deadline = time.time() - 1
        db.get(JobLock, jobs.scope()).expires = time.time() - 1
    expired = jobs.get(j["id"])
    assert expired["status"] == "error" and len(expired["result"]["scenarios"]) == 1
    with pytest.raises(RuntimeError):
        jobs.store(j["id"], "old", {}, "passed")
    assert jobs.enqueue("all", "next-expiry-request-1234")["status"] == "queued"


def test_deployment_scope_cannot_read_or_claim_other_job(runner, monkeypatch):
    j = jobs.enqueue("all", "scope-request-key-1234")
    monkeypatch.setenv("TEST_DEPLOYMENT_ID", "other-copy")
    with pytest.raises(HTTPException) as e:
        jobs.get(j["id"])
    assert e.value.status_code == 404 and jobs.claim("other-worker") is None


def test_request_key_cannot_change_suite(runner):
    jobs.enqueue("all", "same-suite-key-1234")
    with pytest.raises(HTTPException) as e:
        jobs.enqueue("inspection", "same-suite-key-1234")
    assert e.value.status_code == 409


def test_worker_persists_progress_and_terminal_status(runner, monkeypatch):
    j = jobs.enqueue("connectivity", "worker-success-1234")

    async def execute(suite, progress):
        result = {"scenarios": [{"id": 1, "status": "passed"}], "total": 1}
        progress(result)
        assert jobs.get(j["id"])["status"] == "running"
        return result, "passed"

    monkeypatch.setattr(worker, "execute", execute)
    assert asyncio.run(worker.process_one("worker"))
    assert jobs.get(j["id"])["status"] == "passed"
    assert not asyncio.run(worker.process_one("worker"))


def test_worker_error_is_redacted_and_releases_lock(runner, monkeypatch):
    j = jobs.enqueue("all", "worker-error-123456")

    async def execute(suite, progress):
        raise RuntimeError("private-secret-do-not-store")

    monkeypatch.setattr(worker, "execute", execute)
    asyncio.run(worker.process_one("worker"))
    result = jobs.get(j["id"])
    assert result["status"] == "error" and "private-secret" not in str(result)
    assert jobs.enqueue("all", "after-error-request-1234")["status"] == "queued"


def test_inspection_does_not_mistake_unsigned_denial_for_vendor_block(runner, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "trend-gateway")
    from services import trend_transport

    monkeypatch.setattr(
        trend_transport, "tool_map", lambda _: {"search_hotels": "exact-advertised-name"}
    )

    async def session(server, fn):
        return SimpleNamespace(
            isError=True,
            content=[SimpleNamespace(text="Missing, expired or invalid gateway capability")],
        )

    monkeypatch.setattr(cases.mcp_client, "with_session", session)
    assert asyncio.run(cases.inspection("request")) == ("failed", "CONTENT_BLOCK_NOT_OBSERVED")
    assert asyncio.run(cases.inspection("response"))[0] == "unavailable"


def test_inspection_records_exact_content_rejection(runner, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "agentcore-offline")

    async def session(server, fn):
        return SimpleNamespace(isError=True, content=[SimpleNamespace(text="AI_GUARD_BLOCK")])

    monkeypatch.setattr(cases.mcp_client, "with_session", session)
    assert asyncio.run(cases.inspection("request"))[0] == "passed"
    assert cases.case_plan("inspection")[0][2] == "offline marker simulation"


def test_no_inspector_is_unavailable_not_passed(runner):
    assert asyncio.run(cases.inspection("request"))[0] == "unavailable"


@pytest.mark.parametrize(
    "failure", [ConnectionError("private"), ExceptionGroup("private", [ConnectionError("private")])]
)
def test_case_executor_separates_failure_and_transport_block(runner, monkeypatch, failure):
    monkeypatch.setattr(cases, "snapshot", lambda: "unchanged")
    monkeypatch.setattr(cases, "emit", lambda *a, **kw: None)
    monkeypatch.setattr(cases.mcp_client, "discover", AsyncMock(side_effect=failure))
    monkeypatch.setattr(cases, "business", AsyncMock(side_effect=HTTPException(503, "private")))
    result, status = asyncio.run(cases.execute("connectivity", lambda r: None))
    assert status == "blocked" and [c["status"] for c in result["scenarios"]] == [
        "blocked",
        "blocked",
        "passed",
    ]
    assert result["no_mutations"] and "private" not in str(result)


def test_mismatched_worker_profile_is_not_ready(runner, monkeypatch):
    client, _ = runner
    login(client)
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "agentcore-offline")
    assert not jobs.capabilities()["ready"]
    assert launch(client).status_code == 503


def test_legacy_web_endpoints_cannot_bypass_the_durable_launcher(runner):
    from services.api import app
    from services.auth import current

    client, _ = runner
    login(client)
    assert client.post("/monitor/runs").status_code == 409
    app.dependency_overrides[current] = lambda: SimpleNamespace(human="admin")
    try:
        assert client.post("/scenarios/run").status_code == 409
    finally:
        app.dependency_overrides.clear()
