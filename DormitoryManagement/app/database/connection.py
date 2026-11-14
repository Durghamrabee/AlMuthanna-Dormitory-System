from contextlib import contextmanager
from pathlib import Path
import os
from threading import RLock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from .migrations import upgrade


def app_data_directory():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "AlMuthannaDormitoryNative"


class Database:
    def __init__(self, path=None):
        self.path = Path(path or app_data_directory() / "db.sqlite3").resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.engine = create_engine("sqlite+pysqlite:///" + self.path.as_posix(), poolclass=NullPool,
                                    connect_args={"timeout": 20, "check_same_thread": False})
        event.listen(self.engine, "connect", self._configure)

    @staticmethod
    def _configure(connection, _):
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=20000")
        cursor.close()

    def initialize(self, seed=True):
        with self.lock:
            upgrade(self.engine, self.path)
            if seed:
                from .seed import load_reference_data
                load_reference_data(self)
        return self

    @contextmanager
    def session(self, write=False):
        # SQLite has one writer; IMMEDIATE acquires it before checking capacity.
        with self.lock:
            with self.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")
                session = Session(bind=connection, expire_on_commit=False)
                try:
                    yield session
                    session.flush()
                    connection.commit()
                except Exception:
                    session.rollback()
                    connection.rollback()
                    raise
                finally:
                    session.close()

    def dispose(self):
        self.engine.dispose()
