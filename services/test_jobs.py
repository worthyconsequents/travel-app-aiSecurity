"""Durable local worker contract. AWS dispatch is deliberately not enabled."""

import hashlib
import os
import time

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from services.agentcore.transport import deployment_profile
from services.db import Session, TestJob, TestJobLock, TestWorkerPresence

SUITES = {
    "all": "All safe checks",
    "connectivity": "Connectivity",
    "authorization": "Authorization",
    "inspection": "Inspection",
    "tool-changes": "Tool changes (isolated experiment)",
}
ACTIVE = {"queued", "running"}


def scope():
    return os.getenv("TEST_DEPLOYMENT_ID", deployment_profile())


def cloud_configured():
    return (
        os.getenv("APP_MODE") == "aws-demo"
        and os.getenv("ENABLE_AWS_TREND_GATEWAY") == "true"
        and os.getenv("MODEL_MODE", "mock") == "mock"
        and os.getenv("TEST_RUNNER_ENABLED") == "true"
        and os.getenv("TEST_RUNNER_BACKEND") == "kubernetes-cronjob"
        and deployment_profile() == "trend-gateway"
    )


def worker_freshness():
    return 150 if cloud_configured() else 15


def deadline_seconds():
    return 600 if cloud_configured() else 180


def configured():
    # Cloud operator authorization/dispatch must be completed in the AWS session.
    return cloud_configured() or (
        os.getenv("APP_MODE", "local") == "local"
        and os.getenv("MODEL_MODE", "mock") == "mock"
        and os.getenv("TEST_RUNNER_ENABLED") == "true"
        and os.getenv("TEST_RUNNER_BACKEND", "local-worker") == "local-worker"
        and deployment_profile() in {"local", "agentcore-offline", "trend-gateway"}
    )


def capabilities():
    ready = False
    if configured():
        with Session() as db:
            worker = db.get(TestWorkerPresence, scope())
            ready = bool(
                worker
                and worker.profile == deployment_profile()
                and worker.at > time.time() - worker_freshness()
            )
    return {
        "enabled": configured(),
        "ready": ready,
        "backend": "kubernetes-cronjob" if cloud_configured() else "local-worker",
        "suites": [
            {"id": k, "name": v}
            for k, v in SUITES.items()
            if k != "tool-changes" or tool_changes_enabled()
        ],
        "message": "Ready for safe synthetic checks."
        if ready
        else (
            "Scheduled AWS test worker has not checked in."
            if cloud_configured()
            else "Local test worker is stopped or disabled. AWS execution is not enabled."
        ),
        "max_seconds": deadline_seconds(),
    }


def public(job):
    return {
        k: getattr(job, k)
        for k in ("id", "started", "finished", "profile", "suite", "status", "result")
    }


def expire(db, now):
    # No replay after timeout: a restarted worker cannot resume partial tests.
    for row in db.scalars(
        select(TestJob).where(
            TestJob.scope == scope(), TestJob.status.in_(ACTIVE), TestJob.deadline <= now
        )
    ):
        db.execute(
            update(TestJob)
            .where(TestJob.id == row.id, TestJob.status.in_(ACTIVE))
            .values(
                status="error",
                finished=now,
                result=row.result
                | {"error": "Test worker stopped or execution deadline expired. Start a new run."},
            )
        )
    db.execute(delete(TestJobLock).where(TestJobLock.scope == scope(), TestJobLock.expires <= now))


def tool_changes_enabled():
    from services.tool_change_tests import enabled

    return enabled()


def enqueue(suite, request_key, operator=None):
    if not configured():
        raise HTTPException(403, "Test execution is disabled for this environment")
    if cloud_configured() and (not isinstance(operator, str) or len(operator) != 32):
        raise HTTPException(403, "Verified cloud operator required")
    if suite == "tool-changes" and not tool_changes_enabled():
        raise HTTPException(403, "Tool-change fixture is disabled")
    if suite not in SUITES:
        raise HTTPException(422, "Unknown test suite")
    job_id = hashlib.sha256((scope() + ":" + request_key).encode()).hexdigest()[:32]
    now = time.time()
    try:
        with Session.begin() as db:
            expire(db, now)
            previous = db.get(TestJob, job_id)
            if previous:
                if previous.suite != suite:
                    raise HTTPException(409, "Request key was already used for another suite")
                return public(previous)
            worker = db.get(TestWorkerPresence, scope())
            if (
                not worker
                or worker.profile != deployment_profile()
                or worker.at <= now - worker_freshness()
            ):
                raise HTTPException(503, "Test worker is not available")
            db.add(TestJobLock(scope=scope(), job_id=job_id, expires=now + deadline_seconds()))
            db.flush()  # Unique scope lock serializes launches across API processes.
            from services.test_cases import case_plan

            row = TestJob(
                id=job_id,
                scope=scope(),
                profile=deployment_profile(),
                suite=suite,
                started=now,
                deadline=now + deadline_seconds(),
                status="queued",
                result={
                    "scenarios": [],
                    "total": len(case_plan(suite)),
                    **({"operator_id": operator} if operator else {}),
                },
            )
            db.add(row)
            db.flush()
            return public(row)
    except IntegrityError:
        # A concurrent identical retry returns the same durable run.
        with Session() as db:
            previous = db.get(TestJob, job_id)
            if previous and previous.suite == suite:
                return public(previous)
        raise HTTPException(409, "A test run is already queued or running") from None


def recent(sessions=None):
    with (sessions or Session).begin() as db:
        expire(db, time.time())
        return [
            public(row)
            for row in db.scalars(
                select(TestJob)
                .where(TestJob.scope == scope())
                .order_by(TestJob.started.desc())
                .limit(20)
            )
        ]


def get(job_id):
    with Session.begin() as db:
        expire(db, time.time())
        row = db.get(TestJob, job_id)
        if not row or row.scope != scope():
            raise HTTPException(404, "Test run not found")
        return public(row)


def presence():
    values = {"at": time.time(), "profile": deployment_profile()}
    try:
        with Session.begin() as db:
            changed = db.execute(
                update(TestWorkerPresence)
                .where(TestWorkerPresence.scope == scope())
                .values(**values)
            ).rowcount
            if not changed:
                db.add(TestWorkerPresence(scope=scope(), **values))
    except IntegrityError:
        # Another worker registered the same deployment concurrently.
        with Session.begin() as db:
            db.execute(
                update(TestWorkerPresence)
                .where(TestWorkerPresence.scope == scope())
                .values(**values)
            )


def claim(owner):
    with Session.begin() as db:
        now = time.time()
        expire(db, now)
        lock = db.get(TestJobLock, scope())
        if not lock:
            return None
        result = db.execute(
            update(TestJob)
            .where(
                TestJob.id == lock.job_id,
                TestJob.scope == scope(),
                TestJob.profile == deployment_profile(),
                TestJob.status == "queued",
                TestJob.deadline > now,
            )
            .values(status="running", owner=owner, heartbeat=now)
            .returning(TestJob.id)
        ).scalar()
        return result


def store(job_id, owner, result, status=None):
    with Session.begin() as db:
        now = time.time()
        previous = db.get(TestJob, job_id)
        if previous and previous.scope == scope() and previous.result.get("operator_id"):
            result = result | {"operator_id": previous.result["operator_id"]}
        values = {"result": result, "heartbeat": now}
        if status:
            values.update(status=status, finished=now)
        changed = db.execute(
            update(TestJob)
            .where(
                TestJob.id == job_id,
                TestJob.scope == scope(),
                TestJob.owner == owner,
                TestJob.status == "running",
                TestJob.deadline > now,
            )
            .values(**values)
        ).rowcount
        if not changed:
            raise RuntimeError("Test lease is no longer valid")
        if status:
            db.execute(
                delete(TestJobLock).where(
                    TestJobLock.scope == scope(), TestJobLock.job_id == job_id
                )
            )
