"""add_enhanced_ride_features_and_vehicle_categories

Revision ID: 00f385822cfe
Revises: 0230216f4fdc
Create Date: 2026-05-19 20:48:01.410411

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '00f385822cfe'
down_revision = '0230216f4fdc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create new enum types if they don't exist
    connection = op.get_bind()

    # Check and create triptype enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'triptype'"))
    if not result.fetchone():
        op.execute("CREATE TYPE triptype AS ENUM ('one_way', 'round_trip', 'rental', 'outstation', 'airport_pickup', 'airport_drop')")

    # Check and create vehiclecategory enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'vehiclecategory'"))
    if not result.fetchone():
        op.execute("CREATE TYPE vehiclecategory AS ENUM ('mini', 'sedan', 'suv', 'premium')")

    # Add saved_places to users
    op.add_column('users', sa.Column('saved_places', postgresql.JSON(astext_type=sa.Text()), nullable=True))

    # Create vehicle_categories table
    op.create_table(
        'vehicle_categories',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('name', sa.String(50), unique=True, nullable=False),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('seater_capacity', sa.Integer(), default=4),
        sa.Column('base_fare', sa.Float(), default=80.0),
        sa.Column('per_km_rate', sa.Float(), default=14.0),
        sa.Column('example_vehicles', postgresql.JSON(astext_type=sa.Text()), default=list),
        sa.Column('features', postgresql.JSON(astext_type=sa.Text()), default=list),
        sa.Column('icon_name', sa.String(100), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('display_order', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'))
    )

    # Create rides_enhanced table (new comprehensive rides table)
    op.create_table(
        'rides_enhanced',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('driver_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('drivers.id'), nullable=True),

        # Trip Details
        sa.Column('trip_type', sa.String(), default='one_way', nullable=False),
        sa.Column('vehicle_category', sa.String(), default='mini', nullable=False),

        # Locations
        sa.Column('pickup_location', sa.String(255), nullable=False),
        sa.Column('dropoff_location', sa.String(255), nullable=True),
        sa.Column('pickup_lat', sa.Float(), nullable=False),
        sa.Column('pickup_lng', sa.Float(), nullable=False),
        sa.Column('dropoff_lat', sa.Float(), nullable=True),
        sa.Column('dropoff_lng', sa.Float(), nullable=True),
        sa.Column('stops', postgresql.JSON(astext_type=sa.Text()), default=list),

        # Timing
        sa.Column('is_scheduled', sa.Boolean(), default=False),
        sa.Column('scheduled_datetime', sa.DateTime(timezone=True), nullable=True),

        # Booking For Someone Else
        sa.Column('booking_for_self', sa.Boolean(), default=True),
        sa.Column('passenger_name', sa.String(100), nullable=True),
        sa.Column('passenger_phone', sa.String(15), nullable=True),
        sa.Column('passenger_notes', sa.Text(), nullable=True),

        # Ride Preferences
        sa.Column('preferences', postgresql.JSON(astext_type=sa.Text()), default=dict),
        sa.Column('driver_notes', sa.Text(), nullable=True),

        # OTP for ride verification
        sa.Column('ride_otp', sa.String(4), nullable=False),
        sa.Column('otp_verified', sa.Boolean(), default=False),

        # Status
        sa.Column('status', sa.String(), default='pending', nullable=False),

        # Fare Breakdown
        sa.Column('base_fare', sa.Float(), default=0.0),
        sa.Column('distance_fare', sa.Float(), default=0.0),
        sa.Column('platform_fee', sa.Float(), default=20.0),
        sa.Column('gst', sa.Float(), default=0.0),
        sa.Column('toll_charges', sa.Float(), default=0.0),
        sa.Column('night_charges', sa.Float(), default=0.0),
        sa.Column('waiting_charges', sa.Float(), default=0.0),
        sa.Column('fare', sa.Float(), default=0.0),

        # Payment
        sa.Column('payment_status', sa.String(), default='pending', nullable=False),
        sa.Column('payment_method', sa.String(50), default='cash'),
        sa.Column('transaction_id', sa.String(100), nullable=True),

        # Distance & ETA
        sa.Column('distance_km', sa.Float(), default=0.0),
        sa.Column('eta_minutes', sa.Integer(), default=5),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'))
    )

    # Create indexes
    op.create_index('idx_rides_enhanced_user_id', 'rides_enhanced', ['user_id'])
    op.create_index('idx_rides_enhanced_driver_id', 'rides_enhanced', ['driver_id'])
    op.create_index('idx_rides_enhanced_status', 'rides_enhanced', ['status'])

    # Insert default vehicle categories
    vehicle_categories_table = sa.table('vehicle_categories',
        sa.column('id', postgresql.UUID),
        sa.column('name', sa.String),
        sa.column('display_name', sa.String),
        sa.column('description', sa.Text),
        sa.column('seater_capacity', sa.Integer),
        sa.column('base_fare', sa.Float),
        sa.column('per_km_rate', sa.Float),
        sa.column('example_vehicles', postgresql.JSON),
        sa.column('features', postgresql.JSON),
        sa.column('icon_name', sa.String),
        sa.column('is_active', sa.Boolean),
        sa.column('display_order', sa.Integer),
    )

    op.bulk_insert(vehicle_categories_table, [
        {
            'id': uuid.uuid4(),
            'name': 'mini',
            'display_name': 'Mini / Hatchback',
            'description': 'Small car for budget rides',
            'seater_capacity': 4,
            'base_fare': 80.0,
            'per_km_rate': 14.0,
            'example_vehicles': ['WagonR', 'Alto', 'Tiago'],
            'features': ['AC', '4 Seater', 'Budget Friendly'],
            'icon_name': 'car-outline',
            'is_active': True,
            'display_order': 1
        },
        {
            'id': uuid.uuid4(),
            'name': 'sedan',
            'display_name': 'Sedan',
            'description': 'Comfortable rides',
            'seater_capacity': 4,
            'base_fare': 120.0,
            'per_km_rate': 16.0,
            'example_vehicles': ['Dzire', 'Etios', 'Aura'],
            'features': ['AC', '4 Seater', 'Comfortable'],
            'icon_name': 'car-sport-outline',
            'is_active': True,
            'display_order': 2
        },
        {
            'id': uuid.uuid4(),
            'name': 'suv',
            'display_name': 'SUV',
            'description': '6-7 Seater',
            'seater_capacity': 7,
            'base_fare': 180.0,
            'per_km_rate': 22.0,
            'example_vehicles': ['Ertiga', 'Innova', 'Marazzo'],
            'features': ['AC', '6-7 Seater', 'Spacious'],
            'icon_name': 'car-outline',
            'is_active': True,
            'display_order': 3
        },
        {
            'id': uuid.uuid4(),
            'name': 'premium',
            'display_name': 'Premium',
            'description': 'Luxury rides',
            'seater_capacity': 4,
            'base_fare': 250.0,
            'per_km_rate': 28.0,
            'example_vehicles': ['Innova Crysta', 'BYD e6'],
            'features': ['AC', 'Premium', 'Luxury'],
            'icon_name': 'diamond-outline',
            'is_active': True,
            'display_order': 4
        }
    ])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_rides_enhanced_status', 'rides_enhanced')
    op.drop_index('idx_rides_enhanced_driver_id', 'rides_enhanced')
    op.drop_index('idx_rides_enhanced_user_id', 'rides_enhanced')

    # Drop tables
    op.drop_table('rides_enhanced')
    op.drop_table('vehicle_categories')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS triptype')
    op.execute('DROP TYPE IF EXISTS vehiclecategory')

    # Remove saved_places from users
    op.drop_column('users', 'saved_places')
