from pathlib import Path
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections

from apps.common.backup import restore_snapshot


class Command(BaseCommand):
    help = "Restore SQLite while the application is stopped; automatically retain a safety backup."

    def add_arguments(self, parser):
        parser.add_argument("--source", type=Path, required=True)
        parser.add_argument("--confirm-stopped", action="store_true")

    def handle(self, *args, **options):
        if connection.vendor != "sqlite":
            raise CommandError("This restore command supports local SQLite only.")
        if not options["confirm_stopped"]:
            raise CommandError("Stop all application/server/SQLite browser processes first, then use --confirm-stopped.")
        target = connection.settings_dict["NAME"]
        connections.close_all()
        try:
            safety = restore_snapshot(options["source"], target, settings.BASE_DIR / "backups")
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise CommandError(f"Restore failed; check the source and close applications: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Restore completed. Safety backup: {safety}. Run migrate and verify_database before restarting. All sessions were invalidated."))
