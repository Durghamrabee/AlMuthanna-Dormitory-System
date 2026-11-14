"""SQLite snapshot/recovery helpers. Recovery requires all application processes stopped."""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import uuid


def validate_snapshot(path):
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
        if database.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Database integrity check failed.")
        if database.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Database contains broken foreign keys.")
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"django_migrations", "accounts_user", "students_student"} <= tables:
            raise ValueError("Not an AlMuthanna application database.")


def snapshot_database(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.is_symlink() or destination.resolve() == source:
        raise ValueError("Backup destination must be a new file, different from the live database.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects existing backups, even if two commands race.
    with destination.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(destination)) as backup:
                original.backup(backup)
        validate_snapshot(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def restore_snapshot(source, target, safety_directory):
    source = Path(source).resolve(strict=True)
    target = Path(target).absolute()
    if target.is_symlink() or source == target.resolve():
        raise ValueError("Restore source must be different from the live database.")
    validate_snapshot(source)
    # Never replace a WAL database while its sidecars might contain committed work.
    if any(Path(str(target) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Database sidecar files exist. Close the app and have the database checked before restoring.")
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f".restore-{uuid.uuid4().hex}.sqlite3")
    safety = None
    try:
        snapshot_database(source, staged)
        with closing(sqlite3.connect(staged)) as database:
            # Restoring an old backup must not revive old browser sessions.
            database.execute("DELETE FROM django_session")
            database.commit()
        validate_snapshot(staged)
        if target.exists():
            safety = snapshot_database(target, Path(safety_directory) / f"before-restore-{uuid.uuid4().hex}.sqlite3")
        os.replace(staged, target)
    finally:
        staged.unlink(missing_ok=True)
    return safety
