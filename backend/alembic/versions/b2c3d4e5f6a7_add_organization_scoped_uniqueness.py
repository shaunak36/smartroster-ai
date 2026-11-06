"""add organization scoped uniqueness to rosters and public holidays

Revision ID: b2c3d4e5f6a7
Revises: 9a1b2c3d4e5f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "9a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update rosters: replace uq_roster_period with composite (organization_id, year, month)
    with op.batch_alter_table("rosters") as batch_op:
        batch_op.drop_constraint("uq_roster_period", type_="unique")
        batch_op.create_unique_constraint(
            "uq_roster_org_period", ["organization_id", "year", "month"]
        )

    # 2. Update public_holidays: drop global unique on date, create composite (organization_id, date)
    with op.batch_alter_table(
        "public_holidays",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch_op:
        # In SQLite/Alembic, column unique created an unnamed constraint or unique constraint on date
        # batch_alter_table handles dropping unique on date column and adding uq_public_holiday_org_date
        batch_op.drop_constraint("uq_public_holidays_date", type_="unique")
        batch_op.create_unique_constraint(
            "uq_public_holiday_org_date", ["organization_id", "date"]
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "public_holidays",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch_op:
        batch_op.drop_constraint("uq_public_holiday_org_date", type_="unique")
        batch_op.create_unique_constraint("uq_public_holidays_date", ["date"])

    with op.batch_alter_table("rosters") as batch_op:
        batch_op.drop_constraint("uq_roster_org_period", type_="unique")
        batch_op.create_unique_constraint("uq_roster_period", ["year", "month"])
