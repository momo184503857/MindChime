"""Initial versioned asset store and durable task events."""
from alembic import op
from mindchime.db import Base

revision = "0001_local_assets"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind(), checkfirst=True)
    op.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(id UNINDEXED, kind UNINDEXED, title, content)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS search_fts")
    Base.metadata.drop_all(op.get_bind(), checkfirst=True)
