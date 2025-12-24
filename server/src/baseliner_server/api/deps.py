import hashlib
import hmac
from datetime import datetime, timezone
from typing import Generator, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from baseliner_server.core.config import settings
from baseliner_server.core.tenancy import (
    DEFAULT_TENANT_ID,
    TenantContext,
    TenantScopedSession,
    ensure_default_tenant,
    get_tenant_context,
)
from baseliner_server.db.models import Device, DeviceAuthToken, DeviceStatus
from baseliner_server.db.session import SessionLocal


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    """Deterministic token hash with a server-side pepper.

    We never store raw device/enroll tokens.
    """

    msg = (settings.baseliner_token_pepper + token).encode("utf-8")
    return hashlib.sha256(msg).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)


def hash_admin_key(admin_key: str) -> str:
    """Hash an admin key for audit logging.

    We reuse baseliner_token_pepper and add a domain separator so admin key hashes
    cannot collide with token hashes.
    """

    msg = (settings.baseliner_token_pepper + "admin:" + admin_key).encode("utf-8")
    return hashlib.sha256(msg).hexdigest()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        # Phase 0 tenancy plumbing: ensure the default tenant exists for dev/test DBs.
        ensure_default_tenant(db)
        yield db
    finally:
        db.close()


def get_scoped_session(
    tenant: TenantContext = Depends(get_tenant_context), db: Session = Depends(get_db)
) -> TenantScopedSession:
    return TenantScopedSession(db=db, tenant=tenant)


def get_bearer_token(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def require_admin(x_admin_key: Optional[str] = Header(default=None)) -> None:
    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.baseliner_admin_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


def require_admin_actor(x_admin_key: Optional[str] = Header(default=None)) -> str:
    """Validate admin key and return a stable actor id for auditing."""

    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.baseliner_admin_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")
    return hash_admin_key(x_admin_key)


def get_current_device(
    request: Request,
    db: TenantScopedSession = Depends(get_scoped_session),
    token: str = Depends(get_bearer_token),
) -> Device:
    """Resolve the authenticated device by bearer token.

    We prefer the device_auth_tokens table for deterministic token lifecycle handling
    (history + revoked/active + last_used). As a compatibility bridge (tests / pre-migration
    DBs), we can fall back to the legacy devices.auth_token_hash / revoked_auth_token_hash
    fields if no token-row exists yet.
    """

    token_h = hash_token(token)

    tok = db.scalar(select(DeviceAuthToken).where(DeviceAuthToken.token_hash == token_h))
    device: Device | None = tok.device if tok is not None else None

    if device is None:
        # Legacy fallback: map to device by current/most-recently revoked hash so we can return a
        # clear 403 instead of a generic 401. If we find a match and no token row exists, we may
        # lazily create a token-history row (active path only).
        device = db.scalar(
            select(Device).where(
                or_(
                    Device.auth_token_hash == token_h,
                    Device.revoked_auth_token_hash == token_h,
                )
            )
        )
        if not device:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device token")

        if device.revoked_auth_token_hash == token_h:
            # Revoked token presented (deny, but don't mutate device state).
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device token revoked")

        # Active legacy token: create a history row so subsequent lookups are consistent.
        tok = DeviceAuthToken(
            tenant_id=(getattr(device, "tenant_id", None) or DEFAULT_TENANT_ID),
            device_id=device.id,
            token_hash=token_h,
            created_at=getattr(device, "enrolled_at", None) or utcnow(),
        )
        db.add(tok)
        db.flush()

    # Lifecycle gates
    if getattr(device, "status", None) != DeviceStatus.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device deactivated")

    if tok is not None and tok.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device token revoked")

    now = utcnow()
    device.last_seen_at = now

    # Token usage signal: update only for device report posts (to keep this "meaningful").
    try:
        if (
            request.method.upper() == "POST"
            and request.url.path.endswith("/api/v1/device/reports")
            and tok is not None
        ):
            tok.last_used_at = now
            db.add(tok)
    except Exception:
        pass

    db.add(device)
    db.commit()

    return device
