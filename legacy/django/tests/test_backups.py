from pathlib import Path
from contextlib import closing
import sqlite3
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from apps.common.backup import restore_snapshot, snapshot_database


class BackupTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.live = self.root / "live.sqlite3"
        with closing(sqlite3.connect(self.live)) as database:
            database.executescript("""
                CREATE TABLE django_migrations (id INTEGER PRIMARY KEY);
                CREATE TABLE accounts_user (id INTEGER PRIMARY KEY);
                CREATE TABLE students_student (id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE django_session (session_key TEXT PRIMARY KEY);
                INSERT INTO students_student VALUES (1, 'fictional');
                INSERT INTO django_session VALUES ('fictional-session');
            """)

    def test_roundtrip_and_safety_backup(self):
        backup = snapshot_database(self.live, self.root / "snapshot.sqlite3")
        with closing(sqlite3.connect(self.live)) as database:
            database.execute("UPDATE students_student SET name='changed'")
            database.commit()
        safety = restore_snapshot(backup, self.live, self.root / "safety")
        with closing(sqlite3.connect(self.live)) as database:
            self.assertEqual(database.execute("SELECT name FROM students_student").fetchone()[0], "fictional")
            self.assertEqual(database.execute("SELECT COUNT(*) FROM django_session").fetchone()[0], 0)
        with closing(sqlite3.connect(safety)) as database:
            self.assertEqual(database.execute("SELECT name FROM students_student").fetchone()[0], "changed")

    def test_existing_backup_cannot_be_overwritten(self):
        destination = snapshot_database(self.live, self.root / "snapshot.sqlite3")
        with self.assertRaises(FileExistsError):
            snapshot_database(self.live, destination)

    def test_corrupt_source_does_not_change_live_data(self):
        source = self.root / "broken.sqlite3"
        source.write_bytes(b"not a database")
        before = self.live.read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):
            restore_snapshot(source, self.live, self.root / "safety")
        self.assertEqual(self.live.read_bytes(), before)

    def test_sidecar_blocks_restore(self):
        backup = snapshot_database(self.live, self.root / "snapshot.sqlite3")
        Path(str(self.live) + "-wal").touch()
        with self.assertRaisesMessage(ValueError, "sidecar"):
            restore_snapshot(backup, self.live, self.root / "safety")
