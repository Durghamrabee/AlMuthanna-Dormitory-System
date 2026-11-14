from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.common.archives import prepare_archive_restore
from apps.common.models import BackupRecord


@override_settings(ALLOWED_HOSTS=["testserver"], LOCAL_HTTP=True, LOCAL_NO_LOGIN=False)
class ArchiveTests(TransactionTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.settings_override = override_settings(BASE_DIR=self.root, MEDIA_ROOT=self.root / "private_media")
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.actor = User.objects.create_superuser(username="fictional_backup_admin")
        self.client.force_login(self.actor)
        self.media = self.root / "private_media/students/1/fixture.pdf"
        self.media.parent.mkdir(parents=True)
        self.media.write_bytes(b"%PDF-1.4 fictional fixture")

    def test_web_backup_download_and_verified_recovery_staging(self):
        response = self.client.post(reverse("backups"))
        self.assertEqual(response.status_code, 302)
        item = BackupRecord.objects.get()
        self.assertGreater(item.size, 0)
        path = self.root / "backups" / f"bundle-{item.token}.zip"
        with ZipFile(path) as archive:
            self.assertIn("db.sqlite3", archive.namelist())
            self.assertIn("private_media/students/1/fixture.pdf", archive.namelist())
            self.assertNotIn(".env", archive.namelist())
        restored = prepare_archive_restore(path, self.root / "recovery")
        self.assertEqual((restored / "private_media/students/1/fixture.pdf").read_bytes(), self.media.read_bytes())
        response = self.client.get(reverse("backup_download", args=[item.token]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content).startswith(b"PK"))

    def test_non_admin_cannot_create_or_download_full_database_backup(self):
        user = User.objects.create_user(username="fictional_reader")
        self.client.force_login(user)
        self.assertEqual(self.client.post(reverse("backups")).status_code, 403)
        self.assertFalse(BackupRecord.objects.exists())

    def test_path_traversal_archive_is_rejected_without_touching_live_files(self):
        path = self.root / "malicious.zip"
        with ZipFile(path, "w") as archive:
            archive.writestr("db.sqlite3", b"fixture")
            archive.writestr("../escape.txt", b"escape")
            archive.writestr("manifest.json", json.dumps({"format": 1, "sha256": {"db.sqlite3": sha256(b"fixture").hexdigest(), "../escape.txt": sha256(b"escape").hexdigest()}}))
        with self.assertRaisesMessage(ValueError, "Unsafe archive path"):
            prepare_archive_restore(path, self.root / "recovery")
        self.assertFalse((self.root / "escape.txt").exists())
        self.assertFalse((self.root / "recovery").exists())

    def test_backup_preferences_validate_and_persist(self):
        self.assertEqual(self.client.post(reverse("preferences"), {"backup_reminder_days": 0}).status_code, 200)
        self.assertEqual(self.client.post(reverse("preferences"), {"backup_reminder_days": 3}).status_code, 302)
        from apps.common.backup_views import backup_status
        self.assertEqual(backup_status()["backup_days"], 3)
        self.assertTrue(backup_status()["backup_due"])
