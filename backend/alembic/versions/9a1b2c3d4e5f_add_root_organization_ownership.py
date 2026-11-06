"""add organization ownership to root domain records

Revision ID: 9a1b2c3d4e5f
Revises: 7c3d8e1a2b4f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9a1b2c3d4e5f"
down_revision: Union[str, None] = "7c3d8e1a2b4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROOT_TABLES = ("pods", "employees", "brands", "processes", "public_holidays", "rosters")


def _organization_id_column(table: str) -> sa.Column:
    return sa.Column(
        "organization_id",
        sa.Integer(),
        sa.ForeignKey("organizations.id", ondelete="CASCADE", name=f"fk_{table}_organization_id"),
        nullable=True,
    )


def upgrade() -> None:
    bind = op.get_bind()
    organizations = bind.execute(
        sa.text(
            "SELECT id FROM organizations "
            "WHERE name = :name ORDER BY id"
        ),
        {"name": "Demo Operations"},
    ).fetchall()
    if len(organizations) != 1:
        raise RuntimeError(
            "Expected exactly one Demo Operations organization for root backfill"
        )
    organization_id = organizations[0][0]

    for table in ROOT_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(_organization_id_column(table))
        bind.execute(
            sa.text(
                f"UPDATE {table} SET organization_id = :organization_id "
                "WHERE organization_id IS NULL"
            ),
            {"organization_id": organization_id},
        )
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                "organization_id",
                existing_type=sa.Integer(),
                nullable=False,
            )


def downgrade() -> None:
    for table in reversed(ROOT_TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("organization_id")
