"""Add driver documents and cancellation support

Revision ID: driver_docs_v1
Revises:
Create Date: 2026-06-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'driver_docs_v1'
down_revision = None  # Update this with your latest migration ID
branch_labels = None
depends_on = None


def upgrade():
    # Add document fields to drivers table
    op.add_column('drivers', sa.Column('license_document', sa.String(length=500), nullable=True))
    op.add_column('drivers', sa.Column('aadhar_document', sa.String(length=500), nullable=True))
    op.add_column('drivers', sa.Column('verification_notes', sa.String(length=500), nullable=True))

    # Change is_active default to False (needs admin approval)
    op.alter_column('drivers', 'is_active',
               existing_type=sa.Boolean(),
               server_default='false',
               nullable=False)

    # Create ride_cancellations table
    op.create_table('ride_cancellations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('ride_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('cancelled_by', sa.String(length=10), nullable=False),
        sa.Column('canceller_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reason', sa.String(length=100), nullable=False),
        sa.Column('custom_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ride_cancellations_id'), 'ride_cancellations', ['id'], unique=False)
    op.create_index(op.f('ix_ride_cancellations_ride_id'), 'ride_cancellations', ['ride_id'], unique=False)


def downgrade():
    # Drop ride_cancellations table
    op.drop_index(op.f('ix_ride_cancellations_ride_id'), table_name='ride_cancellations')
    op.drop_index(op.f('ix_ride_cancellations_id'), table_name='ride_cancellations')
    op.drop_table('ride_cancellations')

    # Remove document fields from drivers
    op.drop_column('drivers', 'verification_notes')
    op.drop_column('drivers', 'aadhar_document')
    op.drop_column('drivers', 'license_document')

    # Restore is_active default
    op.alter_column('drivers', 'is_active',
               existing_type=sa.Boolean(),
               server_default='true',
               nullable=False)
