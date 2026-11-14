from pathlib import Path
import sqlite3
from zipfile import BadZipFile
from django.core.management.base import BaseCommand, CommandError
from apps.common.archives import prepare_archive_restore


class Command(BaseCommand):
    help = "Verify and extract a backup ZIP into a NEW recovery directory; live data is not changed."

    def add_arguments(self, parser):
        parser.add_argument("--source", type=Path, required=True)
        parser.add_argument("--destination", type=Path, required=True)

    def handle(self, *args, **options):
        try:
            root = prepare_archive_restore(options["source"], options["destination"])
        except (ValueError, OSError, BadZipFile, sqlite3.Error) as exc:
            raise CommandError(f"Recovery preparation failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Verified recovery files: {root}. Stop the app before using restore_database, and restore the matching private_media directory."))
