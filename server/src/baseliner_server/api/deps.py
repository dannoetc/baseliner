import hashlib
import hmac
import uuid
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
from baseliner_server.db.models import AdminKey, AdminScope, Device, DeviceAuthToken, DeviceStatus, Tenant
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


def _parse_tenant_id(raw: Optional[str]) -> uuid.UUID:
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-Tenant-ID header")
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant id")


def _try_parse_tenant_id(raw: Optional[str]) -> uuid.UUID | None:
    """Parse X-Tenant-ID if present, else return None."""
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid X-Tenant-ID: {e}") from e



def _get_tenant(db: Session, tenant_id: uuid.UUID) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def _enforce_tenant_active(tenant: Tenant, *, admin_scope: str) -> None:
    """Enforce tenant.is_active for non-superadmin actors.

    - superadmin: allowed even if tenant is inactive (to recover / manage)
    - tenant_admin + devices: forbidden when tenant is inactive
    """

    if tenant.is_active:
        return
    if admin_scope == "superadmin":
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant disabled")





def get_scoped_session(
    request: Request,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
    _admin_key: AdminKey | None = Depends(get_admin_key_optional),
) -> TenantScopedSession:
    existing = getattr(getattr(request, "state", None), "scoped_session", None)
    if isinstance(existing, TenantScopedSession):
        return existing

    tenant_ctx = get_tenant_context(request) or getattr(getattr(request, "state", None), "tenant_context", None)
    tenant_id: uuid.UUID | None = getattr(tenant_ctx, "id", None)

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        token_h = hash_token(token)
        tok = db.scalar(select(DeviceAuthToken).where(DeviceAuthToken.token_hash == token_h))
        if tok is not None:
            tenant_id = getattr(tok, "tenant_id", None)
        else:
            dev = db.scalar(
                select(Device).where(
                    or_(
                        Device.auth_token_hash == token_h,
                        Device.revoked_auth_token_hash == token_h,
                    )
                )
            )
            if dev is not None:
                tenant_id = getattr(dev, "tenant_id", None) or DEFAULT_TENANT_ID

    if tenant_id is None and x_tenant_id:
        tenant = _get_tenant(db, _parse_tenant_id(x_tenant_id))
        tenant_id = tenant.id

    tenant_id = tenant_id or DEFAULT_TENANT_ID

    scope = getattr(tenant_ctx, "admin_scope", "superadmin")
    if authorization and authorization.lower().startswith("bearer ") and not (x_admin_key or "").strip():
        # Authenticated device request.
        scope = "device"

    tenant = _get_tenant(db, tenant_id)
    _enforce_tenant_active(tenant, admin_scope=scope)

    tenant_ctx = TenantContext(id=tenant_id, admin_scope=scope)
    request.state.tenant_context = tenant_ctx

    scoped = TenantScopedSession(db=db, tenant=tenant_ctx)
    request.state.scoped_session = scoped
    return scoped


def get_bearer_token(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return authorization.split(" ", 1)[1].strip()




def get_admin_key(
    request: Request,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
) -> AdminKey:
    """Authenticate an admin key and establish a tenant context for the request.

    Notes:
      * Admin key lookup is **not** scoped by X-Tenant-ID (except to disambiguate collisions).
      * For **tenant_admin** keys, the effective tenant is always the key's tenant.
        If X-Tenant-ID is provided and differs, we ignore it but expose the mismatch via /admin/whoami.
      * For **superadmin** keys, X-Tenant-ID selects the effective tenant; if missing we default
        to DEFAULT_TENANT_ID.
    """
    raw_key = x_admin_key or settings.baseliner_admin_key
    if not raw_key:
        raise HTTPException(status_code=401, detail="Missing X-Admin-Key")

    key_hash = hash_admin_key(raw_key)
    requested_tenant_id = _try_parse_tenant_id(x_tenant_id)

    candidates = db.scalars(select(AdminKey).where(AdminKey.key_hash == key_hash)).all()
    if not candidates:
        raise HTTPException(status_code=401, detail="Invalid admin key")

    if len(candidates) == 1:
        admin_key = candidates[0]
    else:
        if requested_tenant_id is None:
            raise HTTPException(status_code=400, detail="Ambiguous admin key; provide X-Tenant-ID")
        match = next((c for c in candidates if c.tenant_id == requested_tenant_id), None)
        if match is None:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        admin_key = match

    if admin_key.scope == AdminScope.superadmin:
        effective_tenant_id = requested_tenant_id or DEFAULT_TENANT_ID
        admin_scope = "superadmin"
    else:
        effective_tenant_id = admin_key.tenant_id
        admin_scope = "tenant_admin"

    tenant_mismatch = requested_tenant_id is not None and requested_tenant_id != effective_tenant_id

    tenant = _get_tenant(db, effective_tenant_id)
    _enforce_tenant_active(tenant=tenant, admin_scope=admin_scope)

    request.state.admin_key = admin_key
    request.state.tenant_context = TenantContext(id=effective_tenant_id, admin_scope=admin_scope)
    request.state.requested_tenant_id = str(requested_tenant_id) if requested_tenant_id else None
    request.state.effective_tenant_id = str(effective_tenant_id)
    request.state.tenant_mismatch = tenant_mismatch

    return admin_key


def get_admin_key_optional(
    request: Request,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
) -> AdminKey | None:
    """Optional variant of get_admin_key.

    Used by get_scoped_session so if an admin key is present, we resolve the tenant
    context deterministically before choosing a tenant-scoped session.
    """
    if not x_admin_key:
        return None
    return get_admin_key(request=request, x_admin_key=x_admin_key, x_tenant_id=x_tenant_id, db=db)


def require_admin(_: AdminKey = Depends(get_admin_key)) -> None:
    return None


def require_admin_scope(required: AdminScope):
    """Require at least the given admin scope.

    Scope ordering (higher can do lower):
      - superadmin >= tenant_admin
    """

    allowed: dict[AdminScope, set[AdminScope]] = {
        AdminScope.superadmin: {AdminScope.superadmin},
        AdminScope.tenant_admin: {AdminScope.tenant_admin, AdminScope.superadmin},
    }

    def _dep(admin_key: AdminKey = Depends(get_admin_key)) -> AdminKey:
        scope_val = getattr(admin_key, "scope", AdminScope.tenant_admin)
        scope = scope_val if isinstance(scope_val, AdminScope) else AdminScope(str(scope_val))
        if scope not in allowed.get(required, {required}):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient admin scope",
            )
        return admin_key

    return _dep


def require_admin_actor(admin_key: AdminKey = Depends(get_admin_key)) -> str:
    """Validate admin key and return a stable actor id for auditing."""

    return getattr(admin_key, "key_hash", None) or hash_admin_key(settings.baseliner_admin_key)


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
