import os
import time
import uuid

from sqlalchemy import JSON, Boolean, Float, Integer, String, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def database_url():
    if os.getenv("APP_MODE") == "aws-demo":
        return URL.create(
            "postgresql+psycopg",
            username="travel_demo",
            password=os.environ["DATABASE_PASSWORD"],
            host=os.environ["DATABASE_HOST"],
            port=5432,
            database="travel_demo",
            query={"sslmode": "verify-full", "sslrootcert": "/app/rds-ca.pem"},
        )
    return os.getenv("DATABASE_URL", "sqlite:///travel.db")


engine = create_engine(database_url(), pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Hotel(Base):
    __tablename__ = "hotels"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    destination: Mapped[str]
    description: Mapped[str]
    price: Mapped[int] = mapped_column(Integer)
    rating: Mapped[float] = mapped_column(Float)
    theme: Mapped[str]


class Login(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    human: Mapped[str]
    agent: Mapped[str]
    expires: Mapped[float]


class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    human: Mapped[str]
    hotel_id: Mapped[str]
    check_in: Mapped[str]
    check_out: Mapped[str]
    guests: Mapped[int]
    amount: Mapped[int]
    expires: Mapped[float]


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    human: Mapped[str]
    tool: Mapped[str]
    resource: Mapped[str]
    amount: Mapped[int]
    expires: Mapped[float]
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    human: Mapped[str]
    hotel_id: Mapped[str]
    check_in: Mapped[str]
    check_out: Mapped[str]
    guests: Mapped[int]
    amount: Mapped[int]
    status: Mapped[str] = mapped_column(default="confirmed")
    approval_id: Mapped[str] = mapped_column(String, unique=True)


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    at: Mapped[float] = mapped_column(default=time.time)
    correlation_id: Mapped[str]
    human: Mapped[str]
    agent: Mapped[str]
    tool: Mapped[str]
    server: Mapped[str]
    resource: Mapped[str]
    decision: Mapped[str]
    reason_code: Mapped[str]
    policy_id: Mapped[str]
    approval_state: Mapped[str]
    arguments: Mapped[dict] = mapped_column(JSON)
    downstream: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome: Mapped[str] = mapped_column(default="not_dispatched")


class Activity(Base):
    __tablename__ = "activity"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    at: Mapped[float] = mapped_column(default=time.time)
    correlation_id: Mapped[str] = mapped_column(String, index=True)
    stage: Mapped[str]
    human: Mapped[str]
    agent: Mapped[str]
    tool: Mapped[str]
    audit_id: Mapped[str]
    details: Mapped[dict] = mapped_column(JSON)


class AttackRun(Base):
    __tablename__ = "attack_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    started: Mapped[float] = mapped_column(default=time.time)
    finished: Mapped[float | None]
    profile: Mapped[str]
    status: Mapped[str]
    result: Mapped[dict] = mapped_column(JSON)


class Receipt(Base):
    __tablename__ = "receipts"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    fingerprint: Mapped[str]
    result: Mapped[dict] = mapped_column(JSON)


def uid():
    return uuid.uuid4().hex


def record(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def init():
    Base.metadata.create_all(engine)


class TestJob(Base):
    __tablename__ = "operator_test_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str] = mapped_column(String, index=True)
    profile: Mapped[str]
    suite: Mapped[str]
    started: Mapped[float] = mapped_column(default=time.time)
    finished: Mapped[float | None]
    deadline: Mapped[float]
    status: Mapped[str]
    owner: Mapped[str | None]
    heartbeat: Mapped[float | None]
    result: Mapped[dict] = mapped_column(JSON)


class TestJobLock(Base):
    __tablename__ = "operator_test_locks"
    scope: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str]
    expires: Mapped[float]


class TestWorkerPresence(Base):
    __tablename__ = "operator_test_workers"
    scope: Mapped[str] = mapped_column(String, primary_key=True)
    profile: Mapped[str]
    at: Mapped[float]


class CapabilityReference(Base):
    __tablename__ = "capability_references"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token: Mapped[str] = mapped_column(String(16000))
    expires: Mapped[float] = mapped_column(index=True)
