from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select

from baseliner_server.api.deps import hash_token
from baseliner_server.core.tenancy import DEFAULT_TENANT_ID, TenantScopedSession
from baseliner_server.db.models import Device, DeviceAuthToken


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _revoke_active_device_tokens(
    *, db: TenantScopedSession, device: Device, now: datetime, new_token_row: DeviceAuthToken
) -> None:
    """Revoke any active token-history rows for this device.

    Compatibility bridge: if there are no token rows yet (pre-migration / tests),
    capture + revoke the legacy device.auth_token_hash so future lookups are consistent.
    """

    active: Iterable[DeviceAuthToken] = (
        db.query(DeviceAuthToken)
        .filter(
            DeviceAuthToken.device_id == device.id,
            DeviceAuthToken.tenant_id == device.tenant_id,
            DeviceAuthToken.revoked_at.is_(None),
            DeviceAuthToken.id != new_token_row.id,
        )
        .all()
    )

    if active:
        for t in active:
            t.revoked_at = now
            t.replaced_by_id = new_token_row.id
            db.add(t)
        db.flush()
        return

    # If no token rows exist yet, fall back to legacy state.
    old_hash = getattr(device, "auth_token_hash", None)
    if not old_hash:
        return

    legacy = db.scalar(
        select(DeviceAuthToken).where(
            DeviceAuthToken.token_hash == old_hash,
            DeviceAuthToken.tenant_id == getattr(device, "tenant_id", DEFAULT_TENANT_ID),
        )
    )
    if legacy is None:
        legacy = DeviceAuthToken(
            tenant_id=getattr(device, "tenant_id", DEFAULT_TENANT_ID),
            device_id=device.id,
            token_hash=old_hash,
            created_at=getattr(device, "enrolled_at", None) or now,
        )
        db.add(legacy)
        db.flush()

    legacy.revoked_at = now
    legacy.replaced_by_id = new_token_row.id
    db.add(legacy)
    db.flush()


def rotate_device_token(
    *,
    db: TenantScopedSession,
    device: Device,
    now: datetime | None = None,
    reason: str | None = None,
    actor: str | None = None,
    set_last_used: bool = False,
) -> tuple[str, DeviceAuthToken]:
    """Mint a new device token, revoke any prior ones, and update legacy fields.

    Reason/actor are accepted for audit/debug context even though the current schema
    stores only hash-level history.
    """

    del reason, actor  # reserved for future schema-level audit fields

    now = now or utcnow()
    tenant_id = getattr(device, "tenant_id", DEFAULT_TENANT_ID)

    device_token = secrets.token_urlsafe(32)
    device_token_hash = hash_token(device_token)

    new_tok = DeviceAuthToken(
        tenant_id=tenant_id,
        device_id=device.id,
        token_hash=device_token_hash,
        created_at=now,
        last_used_at=now if set_last_used else None,
    )
    db.add(new_tok)
    db.flush()

    _revoke_active_device_tokens(db=db, device=device, now=now, new_token_row=new_tok)

    old_hash = getattr(device, "auth_token_hash", None)
    if old_hash:
        device.revoked_auth_token_hash = old_hash
        device.token_revoked_at = now

    device.auth_token_hash = device_token_hash
    db.add(device)

    return device_token, new_tok
