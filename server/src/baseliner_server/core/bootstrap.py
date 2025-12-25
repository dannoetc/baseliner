from __future__ import annotations

import hashlib

import sqlalchemy as sa
from sqlalchemy import select

from baseliner_server.core.config import settings
from baseliner_server.core.tenancy import DEFAULT_TENANT_ID, ensure_default_tenant
from baseliner_server.db.models import AdminKey, AdminScope


def _hash_admin_key(admin_key: str) -> str:
    """Hash an admin key using the same scheme as api.deps.hash_admin_key.

    Kept local to avoid import cycles (core -> api).
    """

    msg = (settings.baseliner_token_pepper + "admin:" + admin_key).encode("utf-8")
    return hashlib.sha256(msg).hexdigest()


def ensure_bootstrap_admin_key(db) -> None:
    """Ensure a bootstrap superadmin key exists for the default tenant.

    This makes fresh deployments/dev DBs predictable: if BASELINER_ADMIN_KEY is set,
    the corresponding hash is present in admin_keys for DEFAULT_TENANT_ID.

    Safe to call multiple times.
    """

    ensure_default_tenant(db)

    # If admin_keys isn't present yet (e.g. partially migrated DB), do nothing.
    try:
        bind = db.get_bind()
        if bind is None:
            return
        if not sa.inspect(bind).has_table("admin_keys"):
            return
    except Exception:
        return

    raw = (settings.baseliner_admin_key or "").strip()
    if not raw:
        return

    key_hash = _hash_admin_key(raw)
    existing = db.scalar(
        select(AdminKey).where(AdminKey.tenant_id == DEFAULT_TENANT_ID, AdminKey.key_hash == key_hash)
    )
    if existing is not None:
        return

    db.add(
        AdminKey(
            tenant_id=DEFAULT_TENANT_ID,
            key_hash=key_hash,
            scope=AdminScope.superadmin,
            note="bootstrap",
        )
    )

    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass