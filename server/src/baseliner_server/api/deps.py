import hashlib
import hmac
from datetime import datetime, timezone
from typing import Generator, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from baseliner_server.core.config import settings
from baseliner_server.db.session import SessionLocal
from baseliner_server.db.models import Device


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    # Simple deterministic hash with server-side pepper (do NOT store raw tokens)
    msg = (settings.baseliner_token_pepper + token).encode("utf-8")
    return hashlib.sha256(msg).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_bearer_token(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def require_admin(x_admin_key: Optional[str] = Header(default=None)) -> None:
    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.baseliner_admin_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


def get_current_device(
    db: Session = Depends(get_db),
    token: str = Depends(get_bearer_token),
) -> Device:
    token_h = hash_token(token)
    device = db.scalar(select(Device).where(Device.auth_token_hash == token_h))
    if not device:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device token")

    device.last_seen_at = utcnow()
    db.add(device)
    db.commit()

    return device
