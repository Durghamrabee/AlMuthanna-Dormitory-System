"""Consistent local bundles, including immutable student uploads and a checksum manifest."""
from hashlib import sha256
from itertools import chain
import json
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED

from django.db import transaction
from .backup import snapshot_database, validate_snapshot


@transaction.atomic
def create_archive(database_path, media_root, destination):
    destination, media_root = Path(destination), Path(media_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # IMMEDIATE reserves SQLite's writer while DB and uploads are captured together.
    with TemporaryDirectory(prefix="dormitory-backup-") as temp:
        database = snapshot_database(database_path, Path(temp) / "db.sqlite3")
        with destination.open("xb") as output:
            try:
                with ZipFile(output, "w", ZIP_DEFLATED) as archive:
                    manifest = {}
                    media_files = ((file, "private_media/" + file.relative_to(media_root).as_posix()) for file in media_root.rglob("*") if file.is_file())
                    for path, name in chain([(database, "db.sqlite3")], media_files):
                        if path.is_symlink() or (name.startswith("private_media/") and not path.resolve().is_relative_to(media_root.resolve())):
                            raise ValueError("Links outside private media cannot be backed up.")
                        digest = sha256()
                        with path.open("rb") as source, archive.open(name, "w") as target:
                            while chunk := source.read(1024 * 1024):
                                target.write(chunk)
                                digest.update(chunk)
                        manifest[name] = digest.hexdigest()
                    archive.writestr("manifest.json", json.dumps({"format": 1, "sha256": manifest}, ensure_ascii=False))
            except Exception:
                output.close()
                destination.unlink(missing_ok=True)
                raise
    return destination


def prepare_archive_restore(source, destination):
    """Validate/extract into a new recovery directory; never replace live files here."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Recovery destination must be a new directory.")
    with ZipFile(source) as archive:
        if sum(info.file_size for info in archive.infolist()) > 5 * 1024**3:
            raise ValueError("Backup exceeds the 5 GiB recovery limit.")
        names = archive.namelist()
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ValueError("Invalid or duplicate archive entries.")
        if archive.getinfo("manifest.json").file_size > 10 * 1024**2:
            raise ValueError("Backup manifest is too large.")
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or manifest.get("format") != 1 or not isinstance(manifest.get("sha256"), dict):
            raise ValueError("Unsupported backup format.")
        if set(names) - {"manifest.json"} != set(manifest["sha256"]) or "db.sqlite3" not in names:
            raise ValueError("Archive does not match its manifest.")
        for name in manifest["sha256"]:
            path = PurePosixPath(name)
            if "\\" in name or path.is_absolute() or ".." in path.parts or ":" in name or not (name == "db.sqlite3" or (len(path.parts) > 1 and path.parts[0] == "private_media")):
                raise ValueError("Unsafe archive path.")
        # Paths are validated before writing; no live file is replaced during preparation.
        destination.mkdir(parents=True)
        try:
            for name, expected in manifest["sha256"].items():
                target = destination.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = sha256()
                with archive.open(name) as original, target.open("xb") as output:
                    while chunk := original.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                if digest.hexdigest() != expected:
                    raise ValueError("Backup checksum validation failed.")
            validate_snapshot(destination / "db.sqlite3")
        except Exception:
            # Keep diagnostic staging files; do not touch live data or existing backups.
            raise
    return destination
