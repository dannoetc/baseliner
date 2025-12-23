"""add device auth tokens

Revision ID: b7c8d9e0a1b2
Revises: e1f2a3b4c5d6
Create Date: 2025-12-23 00:00:00

"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0a1b2"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upgrade() -> None:
    op.create_table(
        "device_auth_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("device_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["device_auth_tokens.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_device_auth_tokens_device_id_created_at",
        "device_auth_tokens",
        ["device_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_device_auth_tokens_token_hash",
        "device_auth_tokens",
        ["token_hash"],
        unique=False,
    )
    op.create_index(
        "ix_device_auth_tokens_revoked_at",
        "device_auth_tokens",
        ["revoked_at"],
        unique=False,
    )

    # Backfill from legacy device fields (best-effort).
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, auth_token_hash, revoked_auth_token_hash, enrolled_at, last_seen_at, token_revoked_at "
            "FROM devices"
        )
    ).mappings().all()

    now = _utcnow()
    for r in rows:
        device_id = r["id"]
        enrolled_at = r.get("enrolled_at") or now
        last_seen_at = r.get("last_seen_at")
        token_revoked_at = r.get("token_revoked_at") or now

        auth_hash = r.get("auth_token_hash")
        if auth_hash:
            bind.execute(
                sa.text(
                    "INSERT INTO device_auth_tokens "
                    "(id, device_id, token_hash, created_at, revoked_at, last_used_at, replaced_by_id) "
                    "VALUES (:id, :device_id, :token_hash, :created_at, :revoked_at, :last_used_at, :replaced_by_id)"
                ),
                {
                    "id": uuid.uuid4(),
                    "device_id": device_id,
                    "token_hash": auth_hash,
                    "created_at": enrolled_at,
                    "revoked_at": None,
                    "last_used_at": last_seen_at,
                    "replaced_by_id": None,
                },
            )

        revoked_hash = r.get("revoked_auth_token_hash")
        if revoked_hash:
            bind.execute(
                sa.text(
                    "INSERT INTO device_auth_tokens "
                    "(id, device_id, token_hash, created_at, revoked_at, last_used_at, replaced_by_id) "
                    "VALUES (:id, :device_id, :token_hash, :created_at, :revoked_at, :last_used_at, :replaced_by_id)"
                ),
                {
                    "id": uuid.uuid4(),
                    "device_id": device_id,
                    "token_hash": revoked_hash,
                    "created_at": enrolled_at,
                    "revoked_at": token_revoked_at,
                    "last_used_at": None,
                    "replaced_by_id": None,
                },
            )


def downgrade() -> None:
    op.drop_index("ix_device_auth_tokens_revoked_at", table_name="device_auth_tokens")
    op.drop_index("ix_device_auth_tokens_token_hash", table_name="device_auth_tokens")
    op.drop_index("ix_device_auth_tokens_device_id_created_at", table_name="device_auth_tokens")
    op.drop_table("device_auth_tokens")
