"""One-folder native Windows application; no private database is bundled."""
from pathlib import Path
from importlib.metadata import PackageNotFoundError
import PySide6
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / 'app/resources'), 'app/resources'),
         (str(root / 'docs/reference-sources.md'), 'docs'),
         (str(root / 'docs/report-formatting.md'), 'docs'),
         (str(root / 'docs/student-import.md'), 'docs'),
         (str(root / 'docs/student-documents.md'), 'docs'),
         (str(Path(PySide6.__file__).parent / 'translations/qtbase_ar.qm'), 'PySide6/translations')]
for package in ('PySide6', 'shiboken6', 'SQLAlchemy', 'openpyxl'):
    datas += copy_metadata(package)
for package in ('PySide6_Essentials', 'PySide6_Pdf'):
    # Qt 6.12 splits PDF bindings into a separate wheel; older supported Qt
    # versions carry them in PySide6 itself. Preserve installed wheel notices.
    try:
        datas += copy_metadata(package)
    except PackageNotFoundError:
        pass

analysis = Analysis(
    [str(root / 'main.py')], pathex=[str(root)], datas=datas, binaries=[],
    hiddenimports=collect_submodules('app') + ['sqlalchemy.dialects.sqlite'],
    excludes=[
        'django', 'MySQLdb', 'tkinter', 'pytest', 'tests', 'numpy', 'pandas', 'pymupdf', 'fitz', 'webbrowser',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
        'PySide6.QtWebChannel', 'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets',
        'PySide6.QtNetwork',
        'sqlalchemy.dialects.mysql', 'sqlalchemy.dialects.postgresql',
        'sqlalchemy.dialects.oracle', 'sqlalchemy.dialects.mssql',
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='AlMuthannaNative',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False)
collect = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False,
                  name='AlMuthannaNative')
