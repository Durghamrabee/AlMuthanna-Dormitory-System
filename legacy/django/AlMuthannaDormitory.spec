from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / 'templates'), 'templates'), (str(root / 'static'), 'static')]
for package in ('Django', 'waitress', 'openpyxl', 'Pillow', 'python-dotenv'):
    datas += copy_metadata(package)

analysis = Analysis(
    [str(root / 'desktop_launcher.py')], pathex=[str(root)], binaries=[], datas=datas,
    hiddenimports=collect_submodules('apps') + collect_submodules('desktop') + ['config.settings', 'config.urls'],
    hookspath=[str(root / 'packaging/hooks')],
    excludes=['django.contrib.gis', 'django.db.backends.mysql', 'django.db.backends.oracle', 'django.db.backends.postgresql',
              'MySQLdb', 'weasyprint', 'pymupdf', 'numpy', 'pandas', 'pytest', 'tests'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='AlMuthannaDormitory', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
collect = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='AlMuthannaDormitory')
