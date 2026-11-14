import sqlite3
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction, DatabaseError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.accounts.models import SystemSetting
from apps.accounts.policy import require_account_admin
from apps.audit.services import record_event
from .archives import create_archive
from .models import BackupRecord


class BackupPreferences(forms.Form):
    backup_reminder_days = forms.IntegerField(label="التذكير بالنسخ كل عدد من الأيام", min_value=1, max_value=90)
    pending_application_days = forms.IntegerField(label="تنبيه الطلب المعلق بعد عدد أيام دون تحديث", min_value=0, max_value=365, required=False)
    maintenance_overdue_days = forms.IntegerField(label="تنبيه الصيانة المفتوحة بعد عدد أيام", min_value=0, max_value=365, required=False)
    renewal_notice_days = forms.IntegerField(label="تنبيه التجديد قبل نهاية السنة بعدد أيام", min_value=0, max_value=365, required=False)


def backup_status():
    value = SystemSetting.objects.filter(key="backup_reminder_days").values_list("value", flat=True).first()
    days = value if type(value) is int and 1 <= value <= 90 else 7
    latest = BackupRecord.objects.order_by("-created_at").first()
    file_exists = latest and (settings.BASE_DIR / "backups" / f"bundle-{latest.token}.zip").is_file()
    return {"latest_backup": latest, "backup_days": days, "backup_due": not file_exists or latest.created_at < timezone.now() - timedelta(days=days)}


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def backups(request):
    require_account_admin(request.user)
    if request.method == "POST":
        item = BackupRecord(created_by=request.user)
        path = settings.BASE_DIR / "backups" / f"bundle-{item.token}.zip"
        try:
            create_archive(connection.settings_dict["NAME"], settings.MEDIA_ROOT, path)
            with transaction.atomic():
                item.size = path.stat().st_size
                item.save()
                record_event("backup.created", actor=request.user, target=item)
        except (OSError, ValueError, sqlite3.Error, DatabaseError):
            messages.error(request, "تعذر إنشاء النسخة. تحقق من مساحة القرص وأغلق عمليات الكتابة الأخرى ثم حاول مجدداً.")
        else:
            messages.success(request, "تم إنشاء نسخة تشمل قاعدة البيانات والمستندات. احفظ نسخة منها خارج هذا الجهاز.")
        return redirect("backups")
    context = backup_status()
    context["backups"] = BackupRecord.objects.select_related("created_by").order_by("-created_at")[:30]
    return render(request, "common/backups.html", context)


@login_required
@never_cache
def backup_download(request, token):
    require_account_admin(request.user)
    item = get_object_or_404(BackupRecord, token=token)
    path = settings.BASE_DIR / "backups" / f"bundle-{item.token}.zip"
    if not path.is_file():
        raise Http404
    response = FileResponse(path.open("rb"), as_attachment=True, filename=f"dormitory-backup-{item.created_at:%Y%m%d}.zip")
    response["Cache-Control"] = "private, no-store"
    try:
        record_event("backup.downloaded", actor=request.user, target=item)
    except Exception:
        response.close()
        raise
    return response


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def preferences(request):
    require_account_admin(request.user)
    from .alerts import alert_settings, ALERT_DEFAULTS
    form = BackupPreferences(request.POST if request.method == "POST" else None, initial={"backup_reminder_days": backup_status()["backup_days"], **alert_settings()})
    if request.method == "POST" and form.is_valid():
        setting, _ = SystemSetting.objects.update_or_create(key="backup_reminder_days", defaults={"value": form.cleaned_data["backup_reminder_days"], "description": "فترة تذكير النسخ الاحتياطي بالأيام", "updated_by": request.user})
        record_event("settings.updated", actor=request.user, target=setting, fields=("backup_reminder_days",))
        with transaction.atomic():
            for key in ALERT_DEFAULTS:
                if form.cleaned_data.get(key) is not None:
                    setting, _ = SystemSetting.objects.update_or_create(key=key, defaults={"value": form.cleaned_data[key], "description": form.fields[key].label, "updated_by": request.user})
                    record_event("settings.updated", actor=request.user, target=setting, fields=(key,))
        messages.success(request, "تم حفظ إعدادات التذكير.")
        return redirect("preferences")
    return render(request, "common/form.html", {"form": form, "title": "إعدادات النظام المحلي"})
