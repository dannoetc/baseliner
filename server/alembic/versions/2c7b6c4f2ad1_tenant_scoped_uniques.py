"""tenant-scoped unique constraints for device keys, policies, admin keys

Revision ID: 2c7b6c4f2ad1
Revises: 0f13df607edd
Create Date: 2025-12-30

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "2c7b6c4f2ad1"
down_revision = "0f13df607edd"
branch_labels = None
depends_on = None


def _swap_unique_constraint(table_name: str, old_name: str, new_name: str, columns: list[str]):
    """
    Replace a unique constraint with a new one, using batch mode on SQLite only.

    Batch recreation on PostgreSQL attempts to drop primary keys (breaking FKs),
    so we only use batch_alter_table when the SQLite dialect requires it.
    """

    bind = op.get_bind()
    dialect_name = bind.dialect.name

    inspector = sa.inspect(bind)

    # Skip if the table doesn't exist (deployment environments may be mid-bootstrap).
    if not inspector.has_table(table_name):
        return

    # Skip if the old constraint isn't present (already migrated or schema drift).
    existing_uniques = {uc["name"] for uc in inspector.get_unique_constraints(table_name)}
    if old_name not in existing_uniques:
        # If the new one already exists, avoid re-adding it and return early.
        if new_name in existing_uniques:
            return
        drop_first = False
    else:
        drop_first = True

    if dialect_name == "sqlite":
        # SQLite needs table recreation to add/drop constraints
        with op.batch_alter_table(table_name, recreate="always") as batch_op:
            if drop_first:
                batch_op.drop_constraint(old_name, type_="unique")
            batch_op.create_unique_constraint(new_name, columns)
    else:
        if drop_first:
            op.drop_constraint(old_name, table_name=table_name, type_="unique")
        op.create_unique_constraint(new_name, table_name=table_name, columns=columns)


def upgrade() -> None:
    _swap_unique_constraint(
        "devices", "devices_device_key_key", "uq_devices_tenant_id_device_key", ["tenant_id", "device_key"]
    )
    _swap_unique_constraint(
        "policies", "policies_name_key", "uq_policies_tenant_id_name", ["tenant_id", "name"]
    )
    _swap_unique_constraint(
        "admin_keys", "admin_keys_key_hash_key", "uq_admin_keys_tenant_id_key_hash", ["tenant_id", "key_hash"]
    )


def downgrade() -> None:
    _swap_unique_constraint(
        "admin_keys", "uq_admin_keys_tenant_id_key_hash", "admin_keys_key_hash_key", ["key_hash"]
    )
    _swap_unique_constraint(
        "policies", "uq_policies_tenant_id_name", "policies_name_key", ["name"]
    )
    _swap_unique_constraint(
        "devices", "uq_devices_tenant_id_device_key", "devices_device_key_key", ["device_key"]
    )
