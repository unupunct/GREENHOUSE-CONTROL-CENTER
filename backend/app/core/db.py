"""SQLite engine with settings suited to flash storage."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.engine: Engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}
        )

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, fewer fsyncs
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        self._factory = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        from app.core import models  # noqa: F401  (register tables)

        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def integrity_check(self) -> str:
        with self.engine.connect() as c:
            return str(c.execute(text("PRAGMA integrity_check")).scalar())

    def dispose(self) -> None:
        self.engine.dispose()
