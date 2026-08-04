"""Add static ride_otp to users

Revision ID: b661bb8a4935
Revises: 00f385822cfe
Create Date: 2026-05-20 10:24:39.883483

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b661bb8a4935'
down_revision = '00f385822cfe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add ride_otp column to users with a random 4-digit default for existing users
    op.execute("ALTER TABLE users ADD COLUMN ride_otp VARCHAR(4) DEFAULT LPAD(FLOOR(RANDOM() * 9000 + 1000)::TEXT, 4, '0') NOT NULL")
    # Remove default after adding column (future users will get OTP from model default)
    op.execute("ALTER TABLE users ALTER COLUMN ride_otp DROP DEFAULT")


def downgrade() -> None:
    op.drop_column('users', 'ride_otp')
