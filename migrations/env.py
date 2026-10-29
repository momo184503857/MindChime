import os
from pathlib import Path
from alembic import context
from sqlalchemy import create_engine
from mindchime.db import Base

config = context.config
target_metadata = Base.metadata
path = Path(os.getenv("MINDCHIME_DATA_DIR", "data")).resolve() / "business.sqlite3"
path.parent.mkdir(parents=True, exist_ok=True)
url = f"sqlite:///{path}"

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
