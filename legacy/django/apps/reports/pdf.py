"""Render trusted report HTML offline using the Windows-installed Edge engine."""
from pathlib import Path
import os
import shutil
import subprocess
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError


def browser_executable():
    candidates = [
        Path(os.getenv("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.getenv("ProgramFiles", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    return next((str(path) for path in candidates if path.is_file()), None) or shutil.which("chromium") or shutil.which("google-chrome")


def render_pdf(html):
    browser = browser_executable()
    if not browser:
        raise ValidationError("لم يُعثر على Microsoft Edge. ثبّته محلياً أو استخدم طباعة التقرير وحفظه PDF من المتصفح.")
    with TemporaryDirectory(prefix="almuthanna-report-") as directory:
        root = Path(directory)
        source, destination = root / "report.html", root / "report.pdf"
        source.write_text(html, encoding="utf-8")
        command = [browser, "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                   "--disable-extensions", "--disable-background-networking", "--disable-component-update",
                   f"--user-data-dir={root / 'profile'}", "--no-pdf-header-footer", f"--print-to-pdf={destination}", source.as_uri()]
        try:
            subprocess.run(command, check=True, timeout=45, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValidationError("تعذر إنشاء PDF محلياً. جرّب طباعة التقرير من المتصفح أو أغلق عمليات الطباعة الأخرى.") from exc
        if not destination.exists() or not destination.read_bytes().startswith(b"%PDF-"):
            raise ValidationError("لم يُنشئ محرك الطباعة ملف PDF صالحاً. استخدم زر الطباعة لحفظه من المتصفح.")
        return destination.read_bytes()
