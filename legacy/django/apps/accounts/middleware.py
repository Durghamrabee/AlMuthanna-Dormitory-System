from django.conf import settings
from django.http import HttpResponseForbidden


class LocalOnlyMiddleware:
    """HTTP mode accepts actual loopback peers, independent of Host headers."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (settings.LOCAL_HTTP or settings.LOCAL_NO_LOGIN) and request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}:
            return HttpResponseForbidden("الوصول متاح من هذا الجهاز فقط.", content_type="text/plain; charset=utf-8")
        return self.get_response(request)


class LocalAccessMiddleware:
    """Explicit, reversible local mode; no password or authenticated session is created."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.local_no_login = settings.LOCAL_NO_LOGIN
        if settings.LOCAL_NO_LOGIN:
            from django.contrib.auth.hashers import make_password
            from django.core.exceptions import ImproperlyConfigured
            from django.shortcuts import redirect
            from .models import User

            if request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}:
                return HttpResponseForbidden("الوصول متاح من هذا الجهاز فقط.")
            if request.path.startswith("/accounts/"):
                return redirect("home")
            if not request.path.startswith(settings.STATIC_URL):
                # Persistent technical actor keeps existing foreign keys/audit history valid.
                # A reserved name collision must never silently elevate an existing account.
                user, _ = User.objects.get_or_create(username="__local_operator__", defaults={
                    "password": make_password(None), "first_name": "المشغل المحلي",
                    "is_active": True, "is_superuser": True, "is_staff": False,
                })
                if user.has_usable_password() or not user.is_active or not user.is_superuser or user.is_staff:
                    raise ImproperlyConfigured("The reserved local operator conflicts with an existing account.")
                request.user = user
                request._cached_user = user
        return self.get_response(request)
