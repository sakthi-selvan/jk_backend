"""add_auto_and_bike_vehicle_categories

Revision ID: f1a2b3c4d5e6
Revises: 00f385822cfe
Create Date: 2026-07-09 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'e5621693bcd3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'auto' and 'bike' to the vehiclecategory enum
    op.execute("ALTER TYPE vehiclecategory ADD VALUE IF NOT EXISTS 'auto'")
    op.execute("ALTER TYPE vehiclecategory ADD VALUE IF NOT EXISTS 'bike'")

    # Insert auto and bike into vehicle_categories config table
    vehicle_categories_table = sa.table(
        'vehicle_categories',
        sa.column('id', postgresql.UUID(as_uuid=True)),
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
            'name': 'auto',
            'display_name': 'Auto Rickshaw',
            'description': 'Quick auto rickshaw rides',
            'seater_capacity': 3,
            'base_fare': 30.0,
            'per_km_rate': 10.0,
            'example_vehicles': ['Auto Rickshaw'],
            'features': ['3 Seater', 'Budget', 'No AC'],
            'icon_name': 'car-outline',
            'is_active': True,
            'display_order': 0
        },
        {
            'id': uuid.uuid4(),
            'name': 'bike',
            'display_name': 'Bike Taxi',
            'description': 'Fast & affordable bike taxi',
            'seater_capacity': 1,
            'base_fare': 20.0,
            'per_km_rate': 7.0,
            'example_vehicles': ['Bike', 'Scooter'],
            'features': ['1 Seater', 'Fastest', 'Cheapest'],
            'icon_name': 'bicycle-outline',
            'is_active': True,
            'display_order': 0
        },
    ])

    # Update display_order so auto and bike come first
    op.execute("UPDATE vehicle_categories SET display_order = 1 WHERE name = 'auto'")
    op.execute("UPDATE vehicle_categories SET display_order = 2 WHERE name = 'bike'")
    op.execute("UPDATE vehicle_categories SET display_order = 3 WHERE name = 'mini'")
    op.execute("UPDATE vehicle_categories SET display_order = 4 WHERE name = 'sedan'")
    op.execute("UPDATE vehicle_categories SET display_order = 5 WHERE name = 'suv'")
    op.execute("UPDATE vehicle_categories SET display_order = 6 WHERE name = 'premium'")


def downgrade() -> None:
    op.execute("DELETE FROM vehicle_categories WHERE name IN ('auto', 'bike')")
    # Note: PostgreSQL does not support removing values from an enum type
