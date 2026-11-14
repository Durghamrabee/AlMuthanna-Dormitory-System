"""Windows desktop entry point. Build with AlMuthannaDormitory.spec."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import webbrowser


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--install-dir", type=Path)
    parser.add_argument("--no-shortcut", action="store_true")
    parser.add_argument("--shortcut-dir", type=Path)
    parser.add_argument("--no-launch", action="store_true")
    options = parser.parse_args()
    if options.install:
        from desktop.install import install_application
        if not getattr(sys, "frozen", False):
            parser.error("Installation requires the built Windows executable.")
        target = install_application(Path(sys.executable).parent, options.install_dir, not options.no_shortcut, options.shortcut_dir)
        if options.result:
            options.result.write_text(json.dumps({"installed": True, "directory": str(target)}, ensure_ascii=False), encoding="utf-8")
        if not options.no_launch:
            subprocess.Popen([str(target / "AlMuthannaDormitory.exe")], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return
    from desktop.bootstrap import prepare_environment, initialize_database
    data = options.data_dir or Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "AlMuthannaDormitory"
    data = data.resolve()
    from desktop.single_instance import acquire
    if not acquire(data):
        from desktop.server import existing_instance
        import hashlib
        identity = hashlib.sha256(os.path.normcase(str(data)).encode()).hexdigest()[:24]
        for port in range(8000, 8020):
            if existing_instance(port, identity):
                webbrowser.open(f"http://127.0.0.1:{port}")
                return
        if getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "النظام قيد التشغيل أو التجهيز بالفعل. انتظر نافذة التشغيل الحالية.", "الأقسام الداخلية", 0x40)
        return
    data = prepare_environment(data)
    if sys.stdout is None or sys.stderr is None:
        stream = (data / "application.log").open("a", encoding="utf-8", buffering=1)
        sys.stdout, sys.stderr = stream, stream
    migrated = initialize_database()
    from desktop.server import LocalServer
    server = LocalServer()
    if options.smoke_test:
        import tkinter as tk
        probe = tk.Tk()
        probe.withdraw()
        probe.update_idletasks()
        probe.destroy()
        import urllib.request
        from apps.students.models import Student
        from django.conf import settings
        from django.db import connections
        try:
            url = server.start(port=0)
            results = {"migrations_applied": migrated, "database": settings.DATABASES["default"]["ENGINE"], "students": Student.objects.count(), "gui_initialized": True}
            for name, path in {"home": "/", "static": "/static/css/app.css", "map": "/room-map/", "alerts": "/alerts/", "imports": "/students/import/"}.items():
                with urllib.request.urlopen(url + path, timeout=20) as response:
                    results[name] = response.status
            if options.result:
                options.result.write_text(json.dumps(results), encoding="utf-8")
            else:
                print(json.dumps(results))
        finally:
            server.stop()
            connections.close_all()
        return
    from desktop.window import run_window
    run_window(server, data)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        if sys.stderr:
            traceback.print_exc()
        if "--result" in sys.argv:
            index = sys.argv.index("--result")
            Path(sys.argv[index + 1]).write_text(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), encoding="utf-8")
        elif getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "تعذر تشغيل أو تثبيت النظام. أغلق النسخ القديمة وتحقق من صلاحية مجلد البيانات.\n" + str(exc), "الأقسام الداخلية", 0x10)
        raise SystemExit(1)
