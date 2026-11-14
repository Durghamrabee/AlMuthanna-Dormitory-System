"""Install code separately from user data; preserve the previous installation on updates."""
from datetime import datetime
from pathlib import Path
import base64
import os
import shutil
import subprocess
import uuid


def default_program_dir():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs/AlMuthannaDormitory"


def create_shortcut(executable, directory=None, install_root=None):
    script = """
    $ErrorActionPreference = 'Stop'
    $desktop = if ($env:DORM_SHORTCUT_DIR) { $env:DORM_SHORTCUT_DIR } else { [Environment]::GetFolderPath('Desktop') }
    $path = Join-Path $desktop 'أقسام جامعة المثنى.lnk'
    $temporary = Join-Path $desktop ('AlMuthannaDormitory-' + [Guid]::NewGuid().ToString('N') + '.lnk')
    if (Test-Path -LiteralPath $path) { Copy-Item -LiteralPath $path -Destination $temporary }
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($temporary)
    if ((Test-Path -LiteralPath $path) -and $link.TargetPath -and $link.TargetPath -ne $env:DORM_SHORTCUT_EXE) {
        $old = [IO.FileInfo]::new([IO.Path]::GetFullPath($link.TargetPath))
        $root = [IO.Path]::GetFullPath($env:DORM_SHORTCUT_ROOT)
        $sameInstallation = $old.Name -eq 'AlMuthannaDormitory.exe' -and ($old.Directory.FullName -eq $root -or ($old.Directory.Name -like 'version-*' -and $old.Directory.Parent.FullName -eq $root))
        if (-not $sameInstallation) { throw 'An unrelated shortcut already exists.' }
    }
    $link.TargetPath = $env:DORM_SHORTCUT_EXE
    $link.WorkingDirectory = [IO.Path]::GetDirectoryName($env:DORM_SHORTCUT_EXE)
    $link.Description = 'نظام إدارة الأقسام الداخلية - جامعة المثنى'
    $link.Save()
    Move-Item -LiteralPath $temporary -Destination $path -Force
    """
    env = os.environ.copy()
    env["DORM_SHORTCUT_EXE"] = str(Path(executable).resolve())
    env["DORM_SHORTCUT_ROOT"] = str(Path(install_root or Path(executable).parent).resolve())
    if directory:
        env["DORM_SHORTCUT_DIR"] = str(Path(directory).resolve())
    subprocess.run(["powershell.exe", "-NoProfile", "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode()],
                   env=env, check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def install_application(source, destination=None, shortcut=True, shortcut_directory=None):
    source = Path(source).resolve(strict=True)
    requested = Path(destination or default_program_dir()).absolute()
    if requested.is_symlink():
        raise ValueError("لا يمكن استخدام رابط كمجلد تثبيت.")
    destination = requested.resolve()
    if source == destination:
        if shortcut:
            create_shortcut(destination / "AlMuthannaDormitory.exe", shortcut_directory)
        return destination
    if destination.is_relative_to(source) or source.is_relative_to(destination) or destination.is_symlink():
        raise ValueError("اختر مجلد تثبيت مستقلاً عن مجلد الحزمة ومجلد بيانات المستخدم.")
    if any((destination / name).exists() for name in (".env", "db.sqlite3", "private_media")):
        raise ValueError("مجلد التثبيت يحتوي بيانات مستخدم. اختر مجلد برنامج مستقل للحفاظ عليها.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Version directories avoid renaming a tree containing DLLs that Windows may
    # still have open. The shortcut changes only after the entire copy succeeds.
    destination.mkdir(exist_ok=True)
    staging = destination / f"version-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    # Explicit allowlist: never package/copy an adjacent .env, DB, uploads or logs.
    shutil.copy2(source / "AlMuthannaDormitory.exe", staging / "AlMuthannaDormitory.exe")
    shutil.copytree(source / "_internal", staging / "_internal")
    if shortcut:
        create_shortcut(staging / "AlMuthannaDormitory.exe", shortcut_directory, destination)
    return staging
