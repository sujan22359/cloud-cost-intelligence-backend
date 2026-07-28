"""create organization_knowledge table

Revision ID: 001_create_organization_knowledge
Revises: 
Create Date: 2026-07-22

"""
from alembic import op
import sqlalchemy as sa

revision = '001_create_organization_knowledge'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'organization_knowledge',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('month', sa.String(length=50), nullable=True),
        sa.Column('tags', sa.String(length=255), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('organization_knowledge')
