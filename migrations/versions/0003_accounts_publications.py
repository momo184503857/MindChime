"""Local ownership and published snapshots (idempotent for upgraded local envelopes)."""

import sqlalchemy as sa
from alembic import op

revision = "0003_accounts_publications"
down_revision = "0002_monotonic_events"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if "owner_user_id" not in {c["name"] for c in sa.inspect(connection).get_columns("records")}:
        op.add_column("records", sa.Column("owner_user_id", sa.String(), nullable=True))
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_records_owner_user_id ON records(owner_user_id)"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS published_revisions (record_id TEXT NOT NULL, version INTEGER NOT NULL, manifest JSON NOT NULL, published_at TEXT NOT NULL, PRIMARY KEY(record_id,version))"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS publications (record_id TEXT PRIMARY KEY, version INTEGER NOT NULL, manifest JSON NOT NULL, published_at TEXT NOT NULL)"
    )


def downgrade():
    raise RuntimeError("账号与发布数据需从停服备份恢复，不进行有损降级")
