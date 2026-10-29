"""Preserve SSE cursor monotonicity after private transport cache deletion."""
from alembic import op

revision = "0002_monotonic_events"
down_revision = "0001_local_assets"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("events", recreate="always", table_kwargs={"sqlite_autoincrement": True}):
        pass


def downgrade():
    # Keep the stronger cursor invariant; no user data needs to be rewritten.
    pass
