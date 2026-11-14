from threading import Thread
import json
import urllib.request
import urllib.error


def existing_instance(port, identity):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/system/health/", timeout=.5) as response:
            status = json.load(response)
        return status.get("application") == "almuthanna-dormitory" and status.get("instance") == identity
    except (OSError, ValueError, urllib.error.URLError):
        return False


class LocalServer:
    def __init__(self):
        self.server = None
        self.thread = None
        self.url = None
        self.reused = False

    def start(self, port=None):
        from django.core.wsgi import get_wsgi_application
        from apps.common.health import instance_id
        from waitress.server import create_server
        from waitress.task import ThreadedTaskDispatcher
        from waitress import wasyncore
        ports = [port] if port is not None else range(8000, 8020)
        for number in ports:
            if number and existing_instance(number, instance_id()):
                self.url, self.reused = f"http://127.0.0.1:{number}", True
                return self.url
            try:
                dispatcher = ThreadedTaskDispatcher()
                dispatcher.set_thread_count(4)
                socket_map = {}
                self.server = create_server(get_wsgi_application(), host="127.0.0.1", port=number, map=socket_map, _dispatcher=dispatcher, threads=4)
            except OSError:
                dispatcher.shutdown(timeout=2)
                wasyncore.close_all(socket_map)
                continue
            self.url = f"http://127.0.0.1:{self.server.effective_port}"
            self.thread = Thread(target=self.server.run, name="dormitory-local-server", daemon=True)
            self.thread.start()
            return self.url
        raise RuntimeError("تعذر حجز منفذ محلي. أغلق النسخ القديمة من النظام ثم حاول مجدداً.")

    def stop(self):
        if self.server:
            from waitress import wasyncore
            self.server.task_dispatcher.shutdown(timeout=60)
            if self.server.task_dispatcher.threads:
                raise RuntimeError("هناك عمليات لم تنتهِ بعد. انتظر اكتمالها قبل إيقاف النظام أو استعادة البيانات.")
            wasyncore.close_all(self.server._map)
            if self.thread:
                self.thread.join(timeout=5)
            self.server = None
