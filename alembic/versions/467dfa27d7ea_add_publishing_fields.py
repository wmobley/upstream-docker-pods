"""add_publishing_fields

Revision ID: 467dfa27d7ea
Revises: 778a9dbdeb5e
Create Date: 2025-10-02 12:32:18.268811

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '467dfa27d7ea'
down_revision: Union[str, None] = '778a9dbdeb5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add publishing status fields to all tables."""
    # Add publishing fields to campaigns table
    op.add_column('campaigns', sa.Column('is_published', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('campaigns', sa.Column('published_at', sa.TIMESTAMP(timezone=True), nullable=True))

    # Add publishing fields to stations table
    op.add_column('stations', sa.Column('is_published', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('stations', sa.Column('published_at', sa.TIMESTAMP(timezone=True), nullable=True))

    # Add publishing fields to sensors table
    op.add_column('sensors', sa.Column('is_published', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('sensors', sa.Column('published_at', sa.TIMESTAMP(timezone=True), nullable=True))

    # Add publishing fields to measurements table
    op.add_column('measurements', sa.Column('is_published', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('measurements', sa.Column('published_at', sa.TIMESTAMP(timezone=True), nullable=True))

    # Create indexes for better query performance
    op.create_index('idx_campaigns_is_published', 'campaigns', ['is_published'])
    op.create_index('idx_stations_is_published', 'stations', ['is_published'])
    op.create_index('idx_sensors_is_published', 'sensors', ['is_published'])
    op.create_index('idx_measurements_is_published', 'measurements', ['is_published'])


def downgrade() -> None:
    """Remove publishing status fields from all tables."""
    # Drop indexes
    op.drop_index('idx_measurements_is_published', table_name='measurements')
    op.drop_index('idx_sensors_is_published', table_name='sensors')
    op.drop_index('idx_stations_is_published', table_name='stations')
    op.drop_index('idx_campaigns_is_published', table_name='campaigns')

    # Remove columns from measurements table
    op.drop_column('measurements', 'published_at')
    op.drop_column('measurements', 'is_published')

    # Remove columns from sensors table
    op.drop_column('sensors', 'published_at')
    op.drop_column('sensors', 'is_published')

    # Remove columns from stations table
    op.drop_column('stations', 'published_at')
    op.drop_column('stations', 'is_published')

    # Remove columns from campaigns table
    op.drop_column('campaigns', 'published_at')
    op.drop_column('campaigns', 'is_published')
