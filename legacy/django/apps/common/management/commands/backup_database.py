from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.common.backup import snapshot_database


class Command(BaseCommand):
    help = "Create a consistent SQLite backup without overwriting existing files."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=Path)

    def handle(self, *args, **options):
        if connection.vendor != "sqlite":
            raise CommandError("This backup command supports local SQLite only.")
        output = options["output"] or settings.BASE_DIR / "backups" / f"database-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.sqlite3"
        try:
            destination = snapshot_database(connection.settings_dict["NAME"], output)
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise CommandError(f"Backup failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Backup verified: {destination}. Private media and .env are not included."))
