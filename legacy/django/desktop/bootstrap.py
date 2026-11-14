"""Per-user writable data and migration-safe desktop startup."""
from io import StringIO
from pathlib import Path
import os
import secrets


def prepare_environment(data_dir):
    from dotenv import dotenv_values, set_key
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / ".env"
    if not path.exists():
        path.write_text("", encoding="utf-8")
    existing = dotenv_values(path)
    defaults = {"DJANGO_DEBUG": "false", "DJANGO_LOCAL_HTTP": "true", "DJANGO_LOCAL_NO_LOGIN": "true",
                "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1"}
    if not existing.get("DJANGO_SECRET_KEY") or len(existing["DJANGO_SECRET_KEY"]) < 50:
        set_key(path, "DJANGO_SECRET_KEY", secrets.token_urlsafe(64))
    for key, value in defaults.items():
        if not existing.get(key):
            set_key(path, key, value)
    os.environ["DORMITORY_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    return data_dir


def initialize_database():
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from apps.common.backup import snapshot_database
    from apps.students.models import StudentImportBatch
    from django.conf import settings
    from django.utils import timezone
    from uuid import uuid4
    output = StringIO()
    executor = MigrationExecutor(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    tables = connection.introspection.table_names()
    if pending:
        if tables:
            snapshot_database(connection.settings_dict["NAME"], settings.BASE_DIR / "backups" / f"before-upgrade-{uuid4().hex}.sqlite3")
        call_command("migrate", verbosity=0, stdout=output)
        call_command("setup_roles", stdout=output)
    call_command("check", databases=["default"], stdout=output)
    call_command("verify_database", stdout=output)
    StudentImportBatch.objects.filter(expires_at__lt=timezone.now()).exclude(payload=[]).update(payload=[])
    connection.close()
    return bool(pending)
