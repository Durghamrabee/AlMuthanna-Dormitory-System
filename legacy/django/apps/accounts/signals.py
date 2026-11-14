from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from apps.audit.services import record_event


@receiver(user_logged_in, dispatch_uid="audit_login")
def login_event(sender, request, user, **kwargs):
    record_event("auth.login", actor=user, target=user)


@receiver(user_logged_out, dispatch_uid="audit_logout")
def logout_event(sender, request, user, **kwargs):
    if user:
        record_event("auth.logout", actor=user, target=user)


@receiver(user_login_failed, dispatch_uid="audit_login_failure")
def login_failure(sender, request, **kwargs):
    # Intentionally do not inspect signal credentials (they may contain passwords).
    record_event("auth.login_failed")
