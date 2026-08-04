"""Add rejection_count to rides

Revision ID: c2d96ab73d49
Revises: b661bb8a4935
Create Date: 2026-05-20 10:57:01.112341

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c2d96ab73d49'
down_revision = 'b661bb8a4935'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add rejection_count column to rides_enhanced
    op.execute("ALTER TABLE rides_enhanced ADD COLUMN IF NOT EXISTS rejection_count INTEGER DEFAULT 0 NOT NULL")


def downgrade() -> None:
    op.drop_column('rides_enhanced', 'rejection_count')
    return
    # Old downgrade code removed
    op.create_table('rides_enhanced',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('driver_id', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('trip_type', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('vehicle_category', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('pickup_location', sa.VARCHAR(length=255), autoincrement=False, nullable=False),
    sa.Column('dropoff_location', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
    sa.Column('pickup_lat', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('pickup_lng', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('dropoff_lat', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('dropoff_lng', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('stops', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('is_scheduled', sa.BOOLEAN(), autoincrement=False, nullable=True),
    sa.Column('scheduled_datetime', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True),
    sa.Column('booking_for_self', sa.BOOLEAN(), autoincrement=False, nullable=True),
    sa.Column('passenger_name', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
    sa.Column('passenger_phone', sa.VARCHAR(length=15), autoincrement=False, nullable=True),
    sa.Column('passenger_notes', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('preferences', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('driver_notes', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('ride_otp', sa.VARCHAR(length=4), autoincrement=False, nullable=False),
    sa.Column('otp_verified', sa.BOOLEAN(), autoincrement=False, nullable=True),
    sa.Column('status', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('base_fare', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('distance_fare', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('platform_fee', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('gst', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('toll_charges', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('night_charges', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('waiting_charges', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('fare', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('payment_status', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('payment_method', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
    sa.Column('transaction_id', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
    sa.Column('distance_km', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('eta_minutes', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], name=op.f('rides_enhanced_driver_id_fkey')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('rides_enhanced_user_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('rides_enhanced_pkey'))
    )
    op.create_index(op.f('idx_rides_enhanced_user_id'), 'rides_enhanced', ['user_id'], unique=False)
    op.create_index(op.f('idx_rides_enhanced_status'), 'rides_enhanced', ['status'], unique=False)
    op.create_index(op.f('idx_rides_enhanced_driver_id'), 'rides_enhanced', ['driver_id'], unique=False)
    op.create_table('vehicle_categories',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
    sa.Column('display_name', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
    sa.Column('description', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('seater_capacity', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('base_fare', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('per_km_rate', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('example_vehicles', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('features', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('icon_name', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=True),
    sa.Column('display_order', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('vehicle_categories_pkey')),
    sa.UniqueConstraint('name', name=op.f('vehicle_categories_name_key'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
    # ### end Alembic commands ###
