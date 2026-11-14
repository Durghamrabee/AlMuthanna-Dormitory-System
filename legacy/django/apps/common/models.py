from django.db import models
import uuid


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta:
        abstract = True


class Gender(models.TextChoices):
    MALE = "male", "ذكر"
    FEMALE = "female", "أنثى"


class Availability(models.TextChoices):
    AVAILABLE = "available", "متاح"
    MAINTENANCE = "maintenance", "قيد الصيانة"
    OUT_OF_SERVICE = "out_of_service", "خارج الخدمة"


class BackupRecord(TimeStampedModel):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    size = models.PositiveBigIntegerField("الحجم بالبايت", default=0)
