import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from baseliner_server.api.deps import get_db, hash_token
from baseliner_server.db.models import Device, DeviceAuthToken, DeviceStatus, EnrollToken
from baseliner_server.schemas.enroll import EnrollRequest, EnrollResponse

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


def _revoke_active_device_tokens(
    *,
    db: Session,
    device: Device,
    now: datetime,
    new_token_row: DeviceAuthToken,
) -> None:
    """Revoke any active token-history rows for this device.

    Compatibility bridge: if there are no token rows yet (pre-migration / tests),
    capture + revoke the legacy device.auth_token_hash so future lookups are consistent.
    """

    active = (
        db.query(DeviceAuthToken)
        .filter(
            DeviceAuthToken.device_id == device.id,
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
        return

    # If no token rows exist yet, fall back to legacy state.
    old_hash = getattr(device, "auth_token_hash", None)
    if not old_hash:
        return

    legacy = db.scalar(select(DeviceAuthToken).where(DeviceAuthToken.token_hash == old_hash))
    if legacy is None:
        legacy = DeviceAuthToken(
            device_id=device.id,
            token_hash=old_hash,
            created_at=getattr(device, "enrolled_at", None) or now,
        )
        db.add(legacy)
        db.flush()

    legacy.revoked_at = now
    legacy.replaced_by_id = new_token_row.id
    db.add(legacy)


@router.post("/enroll", response_model=EnrollResponse)
def enroll(payload: EnrollRequest, db: Session = Depends(get_db)) -> EnrollResponse:
    token_hash = hash_token(payload.enroll_token)
    enroll_token = db.scalar(_select_enroll_token_for_update(token_hash))

    if not enroll_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid enroll token")

    if enroll_token.used_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Enroll token already used")

    if enroll_token.expires_at is not None and _as_utc(enroll_token.expires_at) <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Enroll token expired")

    # Create or update device
    device = db.scalar(select(Device).where(Device.device_key == payload.device_key))

    if device is not None and device.status != DeviceStatus.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device is deactivated; cannot enroll",
        )

    now = utcnow()

    # Mint a fresh device token on every enrollment.
    device_token = secrets.token_urlsafe(32)
    device_token_hash = hash_token(device_token)

    if device is None:
        device = Device(
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

        old_hash = device.auth_token_hash

        # Create new token row first so we can link revocations.
        new_tok = DeviceAuthToken(
            device_id=device.id,
            token_hash=device_token_hash,
            created_at=now,
            last_used_at=now,
        )
        db.add(new_tok)
        db.flush()

        _revoke_active_device_tokens(db=db, device=device, now=now, new_token_row=new_tok)

        # Legacy fields retained for clear 403 messaging and compatibility.
        device.revoked_auth_token_hash = old_hash
        device.token_revoked_at = now
        device.auth_token_hash = device_token_hash

        device.last_seen_at = now
        db.add(device)

    # Mark token used.
    enroll_token.used_at = now
    enroll_token.used_by_device_id = device.id
    db.add(enroll_token)

    db.commit()

    return EnrollResponse(device_id=str(device.id), device_token=device_token)
