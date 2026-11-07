"""Add readable triplet name to search index.

Revision ID: 0002_triplet_name
Revises: 0001_initial_schema
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_triplet_name"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add an indexed text value used by library triplet search."""
    op.add_column(
        "triplet_index",
        sa.Column("ivt_name", sa.String(length=255), nullable=False, server_default=""),
    )
    op.create_index("ix_triplet_index_ivt_name", "triplet_index", ["ivt_name"])


def downgrade() -> None:
    """Remove the readable triplet name column and its index."""
    op.drop_index("ix_triplet_index_ivt_name", table_name="triplet_index")
    op.drop_column("triplet_index", "ivt_name")
