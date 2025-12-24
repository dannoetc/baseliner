import secrets
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from baseliner_server.api.deps import get_scoped_session, hash_token
from baseliner_server.core.tenancy import DEFAULT_TENANT_ID, TenantScopedSession
from baseliner_server.db.models import Device, DeviceAuthToken, DeviceStatus, EnrollToken
from baseliner_server.schemas.enroll import EnrollRequest, EnrollResponse
from baseliner_server.services.device_tokens import rotate_device_token

router = APIRouter(tags=["enroll"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """Normalize DB-returned datetimes (sqlite may return naive)."""

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _select_enroll_token_for_update(token_hash: str):
    """Build a SELECT statement for an enroll token.

    We try to lock the row (best-effort) so single-use tokens are harder to race.
    In dialects that don't support FOR UPDATE, SQLAlchemy typically ignores it.
    """

    return (
        select(EnrollToken)
        .where(EnrollToken.token_hash == token_hash)
        .with_for_update()
    )


@router.post("/enroll", response_model=EnrollResponse)
def enroll(payload: EnrollRequest, db: TenantScopedSession = Depends(get_scoped_session)) -> EnrollResponse:
    token_hash = hash_token(payload.enroll_token)
    enroll_token = db.scalar(_select_enroll_token_for_update(token_hash))

    if not enroll_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid enroll token")

    tenant_id = getattr(enroll_token, "tenant_id", None) or DEFAULT_TENANT_ID

    if enroll_token.used_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Enroll token already used")

    if enroll_token.expires_at is not None and _as_utc(enroll_token.expires_at) <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Enroll token expired")

    # Create or update device
    device = db.scalar(select(Device).where(Device.device_key == payload.device_key))

    if device is not None and getattr(device, "tenant_id", None) != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device belongs to a different tenant; cannot enroll",
        )

    if device is not None and device.status != DeviceStatus.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device is deactivated; cannot enroll",
        )

    now = utcnow()

    if device is None:
        # Mint a fresh device token on first enrollment.
        device_token = secrets.token_urlsafe(32)
        device_token_hash = hash_token(device_token)
        device = Device(
            tenant_id=tenant_id,
            device_key=payload.device_key,
            hostname=payload.hostname,
            os=payload.os,
            os_version=payload.os_version,
            arch=payload.arch,
            agent_version=payload.agent_version,
            tags=payload.tags,
            enrolled_at=now,
            last_seen_at=now,
            auth_token_hash=device_token_hash,
        )
        db.add(device)
        db.flush()  # get device.id

        # History row for the minted token.
        db.add(
            DeviceAuthToken(
                tenant_id=tenant_id,
                device_id=device.id,
                token_hash=device_token_hash,
                created_at=now,
                last_used_at=now,
            )
        )

    else:
        # Update metadata + rotate token.
        device.hostname = payload.hostname or device.hostname
        device.os = payload.os or device.os
        device.os_version = payload.os_version or device.os_version
        device.arch = payload.arch or device.arch
        device.agent_version = payload.agent_version or device.agent_version
        device.tags = payload.tags or device.tags

        device_token, _ = rotate_device_token(
            db=db,
            device=device,
            now=now,
            reason="re-enroll",
            actor=None,
            set_last_used=True,
        )

        device.last_seen_at = now
        db.add(device)

    # Mark token used.
    enroll_token.used_at = now
    enroll_token.used_by_device_id = device.id
    db.add(enroll_token)

    db.commit()

    return EnrollResponse(device_id=str(device.id), device_token=device_token)
