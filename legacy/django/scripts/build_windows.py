"""Build a private-data-free Windows distribution and a one-click per-user installer."""
from datetime import datetime
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent


def main():
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', str(ROOT / 'AlMuthannaDormitory.spec')], cwd=ROOT, check=True)
    app = ROOT / 'dist/AlMuthannaDormitory'
    forbidden = [path for path in app.rglob('*') if path.name == '.env' or path.name.endswith('.sqlite3') or any(part in {'private_media', 'private_mail', 'backups'} for part in path.relative_to(app).parts)]
    if forbidden:
        raise RuntimeError('Private database/configuration files were found in the distribution. Packaging stopped.')
    target = ROOT / 'releases' / f'AlMuthannaDormitory-Windows-{datetime.now():%Y%m%d-%H%M%S}.zip'
    target.parent.mkdir(exist_ok=True)
    with ZipFile(target, 'x', ZIP_DEFLATED) as archive:
        for path in app.rglob('*'):
            if path.is_file():
                archive.write(path, 'AlMuthannaDormitory/' + path.relative_to(app).as_posix())
        archive.write(ROOT / 'packaging/Install.cmd', 'Install.cmd')
        archive.write(ROOT / 'docs/windows-desktop.md', 'README-Windows.txt')
    print('Created Windows distribution:', target)


if __name__ == '__main__':
    main()
