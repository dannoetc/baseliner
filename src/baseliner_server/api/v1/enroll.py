import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from baseliner_server.api.deps import get_db, hash_token
from baseliner_server.db.models import Device, DeviceStatus, EnrollToken
from baseliner_server.schemas.enroll import EnrollRequest, EnrollResponse

router = APIRouter(tags=["enroll"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/enroll", response_model=EnrollResponse)
def enroll(payload: EnrollRequest, db: Session = Depends(get_db)) -> EnrollResponse:
    token_hash = hash_token(payload.enroll_token)
    enroll_token = db.scalar(select(EnrollToken).where(EnrollToken.token_hash == token_hash))

    if not enroll_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid enroll token")

    if enroll_token.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Enroll token already used"
        )

    if enroll_token.expires_at is not None and enroll_token.expires_at < utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Enroll token expired")

    # Create or update device
    device = db.scalar(select(Device).where(Device.device_key == payload.device_key))

    if device is not None and device.status != DeviceStatus.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device is deactivated; cannot enroll",
        )

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
            enrolled_at=utcnow(),
            last_seen_at=utcnow(),
            auth_token_hash=device_token_hash,
        )
        db.add(device)
        db.flush()  # get device.id
    else:
        device.hostname = payload.hostname or device.hostname
        device.os = payload.os or device.os
        device.os_version = payload.os_version or device.os_version
        device.arch = payload.arch or device.arch
        device.agent_version = payload.agent_version or device.agent_version
        device.tags = payload.tags or device.tags
        device.status = DeviceStatus.active
        device.deleted_at = None
        device.deleted_reason = None
        device.token_revoked_at = None
        device.revoked_auth_token_hash = None
        device.last_seen_at = utcnow()
        device.auth_token_hash = device_token_hash
        db.add(device)

    enroll_token.used_at = utcnow()
    enroll_token.used_by_device_id = device.id
    db.add(enroll_token)

    db.commit()

    return EnrollResponse(device_id=str(device.id), device_token=device_token)
