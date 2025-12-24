from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest

# Ensure we import the in-repo baseliner_server package rather than any nested clones.
_SERVER_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

from baseliner_server.api.deps import get_db, hash_admin_key
from baseliner_server.core.config import settings
from baseliner_server.core.tenancy import DEFAULT_TENANT_ID, ensure_default_tenant
from baseliner_server.db.base import Base
from baseliner_server.db.models import AdminKey, AdminScope
from baseliner_server.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


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
        ensure_default_tenant(s)
        if not s.scalar(select(AdminKey).where(AdminKey.tenant_id == DEFAULT_TENANT_ID)):
            s.add(
                AdminKey(
                    tenant_id=DEFAULT_TENANT_ID,
                    key_hash=hash_admin_key(settings.baseliner_admin_key),
                    scope=AdminScope.superadmin,
                )
            )
            s.flush()
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

    seed_session = SessionLocal()
    try:
        ensure_default_tenant(seed_session)
        if not seed_session.scalar(select(AdminKey).where(AdminKey.tenant_id == DEFAULT_TENANT_ID)):
            seed_session.add(
                AdminKey(
                    tenant_id=DEFAULT_TENANT_ID,
                    key_hash=hash_admin_key(settings.baseliner_admin_key),
                    scope=AdminScope.superadmin,
                )
            )
            seed_session.commit()
    finally:
        seed_session.close()

    def _get_db_override():
        s = SessionLocal()
        try:
            ensure_default_tenant(s)
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = _get_db_override

    try:
        default_headers = {
            "X-Admin-Key": settings.baseliner_admin_key,
            "X-Tenant-ID": str(DEFAULT_TENANT_ID),
        }
        yield TestClient(app, headers=default_headers)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def admin_headers():
    return {"X-Admin-Key": settings.baseliner_admin_key, "X-Tenant-ID": str(DEFAULT_TENANT_ID)}
