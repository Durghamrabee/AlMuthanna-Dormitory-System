from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4


def restore_bundle(source, data_dir):
    """Caller must stop the server first. Keep safety copies of DB and media."""
    from django.db import connections
    from apps.common.archives import prepare_archive_restore, create_archive
    from apps.common.backup import restore_snapshot
    from apps.audit.services import record_event
    from .bootstrap import initialize_database
    data_dir = Path(data_dir).resolve()
    media = data_dir / "private_media"
    connections.close_all()
    with TemporaryDirectory(prefix="dormitory-recovery-") as temporary:
        recovered = prepare_archive_restore(source, Path(temporary) / "verified")
        safety_zip = data_dir / "backups" / f"before-desktop-restore-{uuid4().hex}.zip"
        create_archive(data_dir / "db.sqlite3", media, safety_zip)
        connections.close_all()
        staging = data_dir / f".media-restore-{uuid4().hex}"
        if (recovered / "private_media").exists():
            shutil.copytree(recovered / "private_media", staging)
        else:
            staging.mkdir()
        previous_media = data_dir / f"private_media.before-restore-{uuid4().hex}"
        safety_db = restore_snapshot(recovered / "db.sqlite3", data_dir / "db.sqlite3", data_dir / "backups")
        moved = False
        try:
            initialize_database()
            connections.close_all()
            if media.exists():
                media.rename(previous_media)
                moved = True
            staging.rename(media)
        except Exception:
            connections.close_all()
            if safety_db:
                restore_snapshot(safety_db, data_dir / "db.sqlite3", data_dir / "backups")
            if moved and not media.exists():
                previous_media.rename(media)
            raise
        record_event("backup.restored")
        connections.close_all()
        return safety_zip
