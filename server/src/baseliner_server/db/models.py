import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CHAR,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GUID(TypeDecorator):
    """
    Cross-database GUID/UUID type.

    - Postgres: UUID(as_uuid=True)
    - SQLite:   CHAR(36) storing string UUIDs
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            # PG driver understands uuid.UUID when as_uuid=True
            return value
        # SQLite: store as string
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(str(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


# Portable JSON column:
# - Postgres: JSONB
# - SQLite: JSON (stored as TEXT; SQLAlchemy handles serialization)
JSON_COL = PG_JSONB().with_variant(JSON(), "sqlite")


class AssignmentMode(str, enum.Enum):
    audit = "audit"
    enforce = "enforce"


class RunStatus(str, enum.Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    partial = "partial"


class StepStatus(str, enum.Enum):
    not_run = "not_run"
    ok = "ok"
    fail = "fail"
    skipped = "skipped"


class LogLevel(str, enum.Enum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    # Agent-provided stable key (e.g., hash of SMBIOS UUID + serial, etc.)
    device_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    os: Mapped[str | None] = mapped_column(String(64), nullable=True)  # "windows"
    os_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    arch: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "x64"
    agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    tags: Mapped[dict] = mapped_column(JSON_COL, nullable=False, default=dict)

    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Store only a hash of the device auth token
    auth_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    runs: Mapped[list["Run"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    assignments: Mapped[list["PolicyAssignment"]] = relationship(back_populates="device", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_devices_last_seen_at", "last_seen_at"),
    )


class EnrollToken(Base):
    __tablename__ = "enroll_tokens"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    used_by_device_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_enroll_tokens_expires_at", "expires_at"),
    )


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    document: Mapped[dict] = mapped_column(JSON_COL, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    assignments: Mapped[list["PolicyAssignment"]] = relationship(back_populates="policy", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_policies_is_active", "is_active"),
    )


class PolicyAssignment(Base):
    __tablename__ = "policy_assignments"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("devices.id", ondelete="CASCADE"))
    policy_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("policies.id", ondelete="CASCADE"))

    mode: Mapped[AssignmentMode] = mapped_column(Enum(AssignmentMode), nullable=False, default=AssignmentMode.enforce)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    device: Mapped["Device"] = relationship(back_populates="assignments")
    policy: Mapped["Policy"] = relationship(back_populates="assignments")

    __table_args__ = (
        UniqueConstraint("device_id", "policy_id", name="uq_policy_assignment_device_policy"),
        Index("ix_policy_assignments_device_id", "device_id"),
        Index("ix_policy_assignments_policy_id", "policy_id"),
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("devices.id", ondelete="CASCADE"))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    effective_policy_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), nullable=False, default=RunStatus.running)

    agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Snapshot of the effective policy used for this run (compiled/merged)
    policy_snapshot: Mapped[dict] = mapped_column(JSON_COL, nullable=False, default=dict)

    # Summary stats: counts, durations, etc.
    summary: Mapped[dict] = mapped_column(JSON_COL, nullable=False, default=dict)

    device: Mapped["Device"] = relationship(back_populates="runs")
    items: Mapped[list["RunItem"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    logs: Mapped[list["LogEvent"]] = relationship(back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_runs_device_id_started_at", "device_id", "started_at"),
    )


class RunItem(Base):
    __tablename__ = "run_items"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    run_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("runs.id", ondelete="CASCADE"))

    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)  # "winget.package", "script.powershell"
    resource_id: Mapped[str] = mapped_column(String(256), nullable=False)  # e.g., winget Id or script name/key
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    compliant_before: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    compliant_after: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reboot_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    status_detect: Mapped[StepStatus] = mapped_column(Enum(StepStatus), nullable=False, default=StepStatus.not_run)
    status_remediate: Mapped[StepStatus] = mapped_column(Enum(StepStatus), nullable=False, default=StepStatus.not_run)
    status_validate: Mapped[StepStatus] = mapped_column(Enum(StepStatus), nullable=False, default=StepStatus.not_run)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    evidence: Mapped[dict] = mapped_column(JSON_COL, nullable=False, default=dict)
    error: Mapped[dict] = mapped_column(JSON_COL, nullable=False, default=dict)

    run: Mapped["Run"] = relationship(back_populates="items")
    logs: Mapped[list["LogEvent"]] = relationship(back_populates="run_item", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_run_items_run_id", "run_id"),
        Index("ix_run_items_resource_type_id", "resource_type", "resource_id"),
    )


class LogEvent(Base):
    __tablename__ = "log_events"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    run_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("runs.id", ondelete="CASCADE"))
    run_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("run_items.id", ondelete="CASCADE"), nullable=True
    )

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    level: Mapped[LogLevel] = mapped_column(Enum(LogLevel), nullable=False, default=LogLevel.info)

    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSON_COL, nullable=False, default=dict)

    run: Mapped["Run"] = relationship(back_populates="logs")
    run_item: Mapped["RunItem"] = relationship(back_populates="logs")

    __table_args__ = (
        Index("ix_log_events_run_id_ts", "run_id", "ts"),
        Index("ix_log_events_run_item_id", "run_item_id"),
    )
