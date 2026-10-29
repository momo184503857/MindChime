"""Versioned business records and durable events, isolated from AI storage.

Records keep a small common envelope; each domain validates its data. Revisions
are immutable snapshots. Mutations and event append operations use short SQLite
transactions so the web process and worker can safely share a local database.
"""
from __future__ import annotations

import copy
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Index, Integer, String, Text, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


def now() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Record(Base):
    __tablename__ = "records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=now)
    updated_at: Mapped[str] = mapped_column(String, default=now)


class Revision(Base):
    __tablename__ = "revisions"
    record_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[dict] = mapped_column(JSON)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String, index=True)
    event: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=now)


Index("ix_record_kind_status", Record.kind, Record.status)
Index("ix_event_topic_id", Event.topic, Event.id)
TRANSIENT_KINDS = {"job", "runtime", "settings", "import_preview", "vector"}


def as_dict(record: Record) -> dict:
    return {key: copy.deepcopy(getattr(record, key)) for key in (
        "id", "kind", "title", "status", "version", "parent_id", "data", "created_at", "updated_at"
    )}


class Database:
    def __init__(self, path: str | Path | None = None):
        self.reset(path or Path(os.getenv("MINDCHIME_DATA_DIR", "data")) / "business.sqlite3")

    def reset(self, path: str | Path):
        if hasattr(self, "engine"):
            self.engine.dispose()
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.path}", connect_args={"timeout": 30})

        @event.listens_for(self.engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")

        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(id UNINDEXED, kind UNINDEXED, title, content)"
            )
        return self

    def create(self, kind: str, title: str, data: dict, status: str = "active",
               parent_id: str | None = None, id: str | None = None) -> dict:
        stamp = now()
        record = Record(id=id or str(uuid.uuid4()), kind=kind, title=title, data=copy.deepcopy(data),
                        status=status, version=1, parent_id=parent_id, created_at=stamp, updated_at=stamp)
        with Session(self.engine) as session, session.begin():
            session.add(record)
            session.flush()
            snapshot = as_dict(record)
            if kind not in TRANSIENT_KINDS:
                session.add(Revision(record_id=record.id, version=1, snapshot=snapshot))
        self._index(snapshot)
        return snapshot

    def get(self, id: str, kind: str | None = None, include_deleted: bool = False) -> dict | None:
        with Session(self.engine) as session:
            record = session.get(Record, id)
            if not record or (kind and record.kind != kind) or (not include_deleted and record.status == "deleted"):
                return None
            return as_dict(record)

    def list(self, kind: str | None = None, parent_id: str | None = None,
             include_deleted: bool = False) -> list[dict]:
        stmt = select(Record).order_by(Record.created_at.desc(), Record.id)
        if kind:
            stmt = stmt.where(Record.kind == kind)
        if parent_id is not None:
            stmt = stmt.where(Record.parent_id == parent_id)
        if not include_deleted:
            stmt = stmt.where(Record.status != "deleted")
        with Session(self.engine) as session:
            return [as_dict(r) for r in session.scalars(stmt)]

    def update(self, id: str, data: dict | None = None, title: str | None = None,
               status: str | None = None, expected_version: int | None = None,
               replace_data: bool = False) -> dict:
        # BEGIN IMMEDIATE serializes read-modify-write across API and worker.
        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            record = session.get(Record, id)
            if record is None:
                session.rollback()
                raise KeyError(id)
            if expected_version is not None and record.version != expected_version:
                session.rollback()
                raise ValueError("该记录已被更新，请刷新后重试")
            if data is not None:
                record.data = copy.deepcopy(data if replace_data else {**record.data, **data})
            if title is not None:
                record.title = title
            if status is not None:
                record.status = status
            record.version += 1
            record.updated_at = now()
            snapshot = as_dict(record)
            if record.kind not in TRANSIENT_KINDS:
                session.add(Revision(record_id=id, version=record.version, snapshot=snapshot))
            session.commit()
        self._index(snapshot)
        return snapshot

    def delete(self, id: str) -> dict:
        return self.update(id, status="deleted")

    def purge(self, id: str) -> None:
        """Remove payloads and old revisions for explicit destructive cleanup."""
        from sqlalchemy import delete
        with self.engine.begin() as connection:
            connection.execute(delete(Revision).where(Revision.record_id == id))
            connection.execute(delete(Record).where(Record.id == id))
            connection.exec_driver_sql("DELETE FROM search_fts WHERE id=?", (id,))

    def revisions(self, id: str) -> list[dict]:
        with Session(self.engine) as session:
            return [copy.deepcopy(r.snapshot) for r in session.scalars(
                select(Revision).where(Revision.record_id == id).order_by(Revision.version.desc())
            )]

    def revision(self, id: str, version: int) -> dict | None:
        with Session(self.engine) as session:
            r = session.get(Revision, (id, version))
            return copy.deepcopy(r.snapshot) if r else None

    def emit(self, topic: str, event: str, data: dict) -> dict:
        with Session(self.engine) as session, session.begin():
            item = Event(topic=topic, event=event, data=copy.deepcopy(data), created_at=now())
            session.add(item)
            session.flush()
            return {"id": item.id, "topic": topic, "event": event, "data": data, "created_at": item.created_at}

    def events(self, topic: str, after: int = 0) -> list[dict]:
        with Session(self.engine) as session:
            return [{"id": e.id, "topic": e.topic, "event": e.event, "data": copy.deepcopy(e.data),
                     "created_at": e.created_at} for e in session.scalars(
                select(Event).where(Event.topic == topic, Event.id > after).order_by(Event.id).limit(500)
            )]

    def claim_job(self) -> dict | None:
        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            record = session.scalar(select(Record).where(Record.kind == "job", Record.status == "queued")
                                    .order_by(Record.created_at, Record.id).limit(1))
            if record is None:
                session.rollback()
                return None
            record.status = "running"
            record.updated_at = now()
            record.version += 1
            snapshot = as_dict(record)
            session.commit()
            return snapshot

    def _index(self, record: dict) -> None:
        # This index is a derived cache; source/version authorization is still
        # checked against live records after every retrieval.
        import json
        import re
        if record["kind"] in TRANSIENT_KINDS:
            return
        text = json.dumps(record["data"], ensure_ascii=False)
        # Character bigrams retain useful CJK matches without rewriting originals.
        def tokenize(value: str) -> str:
            terms = re.findall(r"[A-Za-z0-9_]+", value.lower())
            for run in re.findall(r"[\u3400-\u9fff]+", value):
                terms.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
            return " ".join(terms)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM search_fts WHERE id=?", (record["id"],))
            if record["status"] not in {"deleted", "disabled"}:
                connection.exec_driver_sql("INSERT INTO search_fts(id,kind,title,content) VALUES (?,?,?,?)",
                                           (record["id"], record["kind"], tokenize(record["title"]), tokenize(text)))

    def search(self, query: str, kind: str | None = None, limit: int = 100) -> list[dict]:
        import re
        terms = re.findall(r"[A-Za-z0-9_]+", query.lower())
        for run in re.findall(r"[\u3400-\u9fff]+", query):
            terms.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
        if not terms:
            return []
        expression = " OR ".join('"' + term.replace('"', '') + '"' for term in terms[:64])
        with self.engine.connect() as connection:
            sql = "SELECT id FROM search_fts WHERE search_fts MATCH ?"
            params: list[Any] = [expression]
            if kind:
                sql += " AND kind=?"
                params.append(kind)
            sql += " ORDER BY bm25(search_fts) LIMIT ?"
            params.append(limit)
            ids = [r[0] for r in connection.exec_driver_sql(sql, tuple(params))]
        return [item for id in ids if (item := self.get(id)) and item["status"] != "disabled"]


db = Database()
