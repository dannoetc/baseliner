"""Lightweight helpers for bootstrapping the database schema in dev/test.

This lets local developers spin up the API quickly without needing
Postgres + Alembic migrations; metadata-driven creation is good enough for
SQLite-backed smoke testing.
"""
from __future__ import annotations

from baseliner_server.db import models  # noqa: F401 (register models for metadata)
from baseliner_server.db.base import Base
from baseliner_server.db.session import engine


def ensure_schema() -> None:
    """Create tables if they do not already exist."""
    Base.metadata.create_all(bind=engine)
