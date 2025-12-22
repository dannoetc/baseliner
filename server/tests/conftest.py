from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from baseliner_server.main import app
from baseliner_server.api.deps import get_db, require_admin, require_admin_actor
from baseliner_server.db.base import Base


@pytest.fixture()
def db_engine():
    """
    Temp sqlite DB per test. Keeps tests isolated + avoids cross-thread Session sharing.
    """
    fd, path = tempfile.mkstemp(prefix="baseliner_test_", suffix=".db")
    os.close(fd)

    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=engine)

    try:
        yield engine
    finally:
        engine.dispose()
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass


@pytest.fixture()
def db(db_engine) -> Generator[Session, None, None]:
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


@pytest.fixture()
def client(db_engine) -> Generator[TestClient, None, None]:
    """
    TestClient fixture (generator): overrides deps and clears overrides after test.
    """
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)

    def _get_db_override():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    def _require_admin_override():
        return True

    def _require_admin_actor_override():
        return "test-admin"

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[require_admin] = _require_admin_override
    app.dependency_overrides[require_admin_actor] = _require_admin_actor_override

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
