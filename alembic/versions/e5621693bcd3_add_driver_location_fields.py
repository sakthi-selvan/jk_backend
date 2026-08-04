"""add_driver_location_fields

Revision ID: e5621693bcd3
Revises: c2d96ab73d49
Create Date: 2026-06-19 10:04:55.959422

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5621693bcd3'
down_revision = 'c2d96ab73d49'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('drivers', sa.Column('current_lat', sa.Float(), nullable=True))
    op.add_column('drivers', sa.Column('current_lng', sa.Float(), nullable=True))
    op.add_column('drivers', sa.Column('location_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('drivers', 'location_updated_at')
    op.drop_column('drivers', 'current_lng')
    op.drop_column('drivers', 'current_lat')
