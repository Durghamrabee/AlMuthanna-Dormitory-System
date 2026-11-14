from django.db import models
from django.db.models import F, Q
from apps.common.models import TimeStampedModel


class MaintenanceRequest(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "مفتوح"
        IN_PROGRESS = "in_progress", "قيد التنفيذ"
        COMPLETED = "completed", "مكتمل"
        CANCELLED = "cancelled", "ملغى"

    class Priority(models.TextChoices):
        LOW = "low", "منخفضة"
        NORMAL = "normal", "عادية"
        HIGH = "high", "عالية"
        URGENT = "urgent", "عاجلة"

    # Exactly one target avoids storing contradictory building/room/bed chains.
    building = models.ForeignKey("dormitories.Building", on_delete=models.PROTECT, null=True, blank=True, related_name="maintenance_requests")
    room = models.ForeignKey("dormitories.Room", on_delete=models.PROTECT, null=True, blank=True, related_name="maintenance_requests")
    bed = models.ForeignKey("dormitories.Bed", on_delete=models.PROTECT, null=True, blank=True, related_name="maintenance_requests")
    category = models.CharField("فئة العطل", max_length=100)
    description = models.TextField("الوصف", max_length=4000)
    priority = models.CharField("الأولوية", max_length=6, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField("الحالة", max_length=12, choices=Status.choices, default=Status.OPEN)
    reported_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="reported_maintenance")
    assigned_to = models.ForeignKey("accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="assigned_maintenance")
    completed_at = models.DateTimeField("تاريخ الإنجاز", null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(Q(building__isnull=False, room__isnull=True, bed__isnull=True) | Q(building__isnull=True, room__isnull=False, bed__isnull=True) | Q(building__isnull=True, room__isnull=True, bed__isnull=False)), name="maintenance_exactly_one_target"),
            models.CheckConstraint(condition=Q(status="completed", completed_at__isnull=False) | (~Q(status="completed") & Q(completed_at__isnull=True)), name="maintenance_completion_pair"),
            models.CheckConstraint(condition=Q(completed_at__isnull=True) | Q(completed_at__gte=F("created_at")), name="maintenance_completed_after_report"),
        ]
        indexes = [models.Index(fields=["status", "priority"], name="maintenance_status_priority"), models.Index(fields=["status", "created_at"], name="maintenance_status_created")]


class MaintenanceStatusHistory(TimeStampedModel):
    request = models.ForeignKey(MaintenanceRequest, on_delete=models.PROTECT, related_name="status_history")
    from_status = models.CharField("الحالة السابقة", max_length=12, choices=MaintenanceRequest.Status.choices, blank=True)
    to_status = models.CharField("الحالة الجديدة", max_length=12, choices=MaintenanceRequest.Status.choices)
    changed_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    note = models.TextField("الملاحظة", max_length=2000, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
