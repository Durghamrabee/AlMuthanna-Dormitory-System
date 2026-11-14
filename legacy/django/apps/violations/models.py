from django.db import models
from apps.common.models import TimeStampedModel


class ViolationType(TimeStampedModel):
    name = models.CharField("نوع المخالفة", max_length=150, unique=True)
    is_active = models.BooleanField("فعال", default=True)


class Violation(TimeStampedModel):
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="violations")
    violation_type = models.ForeignKey(ViolationType, on_delete=models.PROTECT)
    occurred_on = models.DateField("تاريخ المخالفة", db_index=True)
    description = models.TextField("الوصف", max_length=4000)
    administrative_action = models.TextField("الإجراء الإداري", max_length=2000)
    responsible_employee = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
