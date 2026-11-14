from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models

from apps.common.models import Gender, TimeStampedModel


class User(AbstractUser):
    class ScopeMode(models.TextChoices):
        GENDER = "gender", "حسب الجنس"
        BUILDING = "building", "بنايات محددة فقط"

    scope_mode = models.CharField("نوع نطاق الوصول", max_length=8, choices=ScopeMode.choices, default=ScopeMode.GENDER)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تعديل", auto_now=True)

    class Meta(AbstractUser.Meta):
        verbose_name = "موظف"
        verbose_name_plural = "الموظفون"
        permissions = [("manage_access", "إدارة حسابات وصلاحيات الموظفين"), ("view_reports", "عرض التقارير"), ("export_reports", "تصدير التقارير")]
        constraints = [models.CheckConstraint(condition=models.Q(scope_mode__in=["gender", "building"]), name="user_valid_scope_mode")]


class UserScope(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scopes")
    gender = models.CharField("نطاق الجنس", max_length=6, choices=Gender.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "gender"], name="unique_user_gender_scope"),
            models.CheckConstraint(condition=models.Q(gender__in=Gender.values), name="scope_valid_gender"),
        ]


class SystemSetting(TimeStampedModel):
    key = models.SlugField("المفتاح", max_length=100, unique=True)
    value = models.JSONField("القيمة")
    description = models.CharField("الوصف", max_length=255)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)


class UserBuildingScope(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="building_scopes")
    building = models.ForeignKey("dormitories.Building", on_delete=models.PROTECT, related_name="staff_scopes")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "building"], name="unique_user_building_scope")]


class LoginThrottle(TimeStampedModel):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    window_started = models.DateTimeField()
