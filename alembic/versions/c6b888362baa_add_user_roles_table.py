"""add user roles table

Revision ID: c6b888362baa
Revises: add_unique_constraint_to_values
Create Date: 2024-11-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c6b888362baa'
down_revision = 'add_unique_constraint_to_values'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_roles',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('username', sa.String(length=128), nullable=False, unique=True),
        sa.Column('role', sa.String(length=32), nullable=False, server_default='READ'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )

    # Seed a default admin to ensure someone can manage roles post-migration
    op.execute(
        """
        INSERT INTO user_roles (username, role)
        SELECT 'wmobley', 'ADMIN'
        WHERE NOT EXISTS (
            SELECT 1 FROM user_roles WHERE lower(username) = 'wmobley'
        )
        """
    )


def downgrade() -> None:
    op.drop_table('user_roles')
