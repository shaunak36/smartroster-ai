"""add model validation constraints

Revision ID: 82817849cdb1
Revises: 192e0faef59d
Create Date: 2026-11-05 23:40:39.495343
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '82817849cdb1'
down_revision: Union[str, None] = '192e0faef59d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("employee_weekly_off_exceptions") as batch_op:
        batch_op.alter_column(
            "approved_at",
            existing_type=sa.DATE(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("employee_weekly_off_exceptions") as batch_op:
        batch_op.alter_column(
            "approved_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DATE(),
            existing_nullable=True,
        )
