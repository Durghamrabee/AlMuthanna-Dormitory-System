"""Build a portable native app, rejecting accidental private data in the bundle."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.fonts import FONT_FILES, FONT_LICENSE
APP_NAME = 'AlMuthannaNative'


def write_shortcut_launcher(path: Path):
    # WScript.Save can fail on Arabic filenames on some Windows installations.
    # Save to an ASCII temporary name, then rename with the Unicode-aware cmdlet.
    script = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$desktop = if ($env:DORM_NATIVE_SHORTCUT_DIR) { $env:DORM_NATIVE_SHORTCUT_DIR } else { [Environment]::GetFolderPath('Desktop') }
$exe = [IO.Path]::GetFullPath($env:DORM_NATIVE_EXE)
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'لم يُعثر على ملف التشغيل. فك الحزمة كاملة أولاً.' }
$description = 'AlMuthannaNative'
$path = Join-Path $desktop 'طلبة الأقسام الداخلية - جامعة المثنى.lnk'
$temporary = Join-Path $desktop ('AlMuthannaNative-' + [Guid]::NewGuid().ToString('N') + '.lnk')
try {
    if (Test-Path -LiteralPath $path) { Copy-Item -LiteralPath $path -Destination $temporary }
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($temporary)
    if ((Test-Path -LiteralPath $path) -and $link.TargetPath -and $link.TargetPath -ne $exe) {
        if ([IO.Path]::GetFileName($link.TargetPath) -ne 'AlMuthannaNative.exe' -or $link.Description -ne $description -or $link.Arguments) { throw 'يوجد اختصار آخر أو مخصص بهذا الاسم؛ تم الحفاظ عليه.' }
    }
    $link.TargetPath = $exe
    $link.WorkingDirectory = [IO.Path]::GetDirectoryName($exe)
    $link.Description = $description
    $link.Save()
    Move-Item -LiteralPath $temporary -Destination $path -Force
    [Console]::WriteLine('تم إنشاء الاختصار. بيانات البرنامج محفوظة في AppData مستقلة عن ملفات التشغيل.')
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
}
"""
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    command = (
        '@echo off\r\nsetlocal\r\nchcp 65001 >nul\r\n'
        'set "DORM_NATIVE_EXE=%~dp0AlMuthannaNative\\AlMuthannaNative.exe"\r\n'
        'if not exist "%DORM_NATIVE_EXE%" set "DORM_NATIVE_EXE=%~dp0dist\\AlMuthannaNative\\AlMuthannaNative.exe"\r\n'
        f'powershell.exe -NoProfile -EncodedCommand {encoded}\r\n'
        'if errorlevel 1 (\r\n echo Shortcut creation failed; existing shortcuts were preserved.\r\n pause\r\n exit /b 1\r\n)\r\n'
        'if not defined DORM_NATIVE_SHORTCUT_DIR pause\r\n'
    )
    path.write_text(command, encoding='ascii', newline='')


def validate_distribution(folder: Path):
    forbidden_directories = {'.venv', '.tools', '.report_previews', 'private_media', 'private_mail', 'backups', 'tests'}
    for path in folder.rglob('*'):
        relative = path.relative_to(folder)
        name = path.name.casefold()
        if (path.is_symlink() or name in {'.env', 'report-profiles.json'} or name.endswith(('.sqlite3', '.sqlite3-wal', '.sqlite3-shm', '.sqlite3-journal'))
                or any(part.casefold() in forbidden_directories for part in relative.parts)):
            raise RuntimeError('Private data or development files found in the distribution. Packaging stopped.')
    if not (folder / f'{APP_NAME}.exe').is_file():
        raise RuntimeError('The native executable was not created.')
    resources = folder / '_internal/app/resources'
    if (any(not (resources / 'fonts' / name).is_file() for name in (*FONT_FILES, FONT_LICENSE, 'Cairo.ttf', 'OFL.txt'))
            or not (resources / 'reference_data/iraq_university.json').is_file()):
        raise RuntimeError('Required Arabic font or reference data is missing.')
    if not (folder / '_internal/PySide6/translations/qtbase_ar.qm').is_file():
        raise RuntimeError('The Arabic Qt translation is missing.')
    for filename in ('QtPdf.pyd', 'QtPdfWidgets.pyd', 'Qt6Pdf.dll', 'Qt6PdfWidgets.dll'):
        if not (folder / '_internal/PySide6' / filename).is_file():
            raise RuntimeError('The native PDF preview library is missing.')


def main():
    if sys.platform != 'win32':
        raise RuntimeError('Build the Windows executable on Windows.')
    if sys.version_info[:2] not in {(3, 12), (3, 13)}:
        raise RuntimeError('Build with Python 3.12 or 3.13, as required by this application.')
    for directory in (ROOT / 'dist', ROOT / 'build'):
        if not directory.resolve().is_relative_to(ROOT):
            raise RuntimeError('Build output must remain inside this native application directory.')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', str(ROOT / 'AlMuthannaNative.spec')], cwd=ROOT, check=True)
    application = ROOT / 'dist' / APP_NAME
    validate_distribution(application)
    shortcut = ROOT / 'CreateDesktopShortcut.cmd'
    write_shortcut_launcher(shortcut)
    releases = ROOT / 'releases'
    releases.mkdir(exist_ok=True)
    filename = f'{APP_NAME}-Windows-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.zip'
    package = releases / filename
    with ZipFile(package, 'x', ZIP_DEFLATED) as archive:
        for path in sorted(application.rglob('*')):
            if path.is_file():
                archive.write(path, APP_NAME + '/' + path.relative_to(application).as_posix())
        archive.write(shortcut, shortcut.name)
        archive.write(ROOT / 'docs/installation.md', 'README-Windows.txt')
        archive.write(ROOT / 'docs/reference-sources.md', 'Reference-Sources.md')
        archive.write(ROOT / 'docs/report-formatting.md', 'Report-Formatting.md')
        archive.write(ROOT / 'docs/student-import.md', 'Student-Import.md')
        archive.write(ROOT / 'docs/student-documents.md', 'Student-Documents.md')
    with ZipFile(package) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('The distribution ZIP failed its integrity check.')
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    package.with_suffix('.zip.sha256').write_text(f'{digest}  {filename}\n', encoding='ascii')
    print(f'Created portable Windows package: {package}')
    print('ZIP integrity and private-data checks passed. Run the built EXE smoke test before release.')


if __name__ == '__main__':
    main()
