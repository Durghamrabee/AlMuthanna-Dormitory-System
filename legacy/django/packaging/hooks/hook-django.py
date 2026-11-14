"""Collect framework resources without the default hook's project db.* copying."""
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

datas, binaries, hiddenimports = collect_all("django", on_error="ignore")
hiddenimports += ["config.settings", "config.urls", "config.wsgi"] + collect_submodules("apps")
datas += collect_data_files("apps", include_py_files=True, includes=["**/migrations/*.py"])
# Never discover/copy the project .env, db.sqlite3, backups or private media.
