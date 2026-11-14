from .models import AuditLog


def record_event(action, *, actor=None, target=None, fields=()):
    """Accept only field names; never serialize arbitrary form/request values."""
    return AuditLog.objects.create(
        actor=actor if actor and actor.is_authenticated else None,
        action=action,
        model_label=target._meta.label_lower if target is not None else "accounts.user",
        object_id=target.pk if target is not None else 0,
        metadata={"fields": list(fields)} if fields else {},
    )
