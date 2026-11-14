from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_GET
from django.utils import timezone

from apps.accounts.policy import require_permission
from .models import Student, StudentImportBatch
from .importing import preview_import, commit_import, template_workbook


class ImportFileForm(forms.Form):
    file = forms.FileField(label="ملف الطلبة XLSX", widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}))


class ImportConfirmForm(forms.Form):
    confirm = forms.BooleanField(label="راجعت البيانات وأؤكد استيراد جميع الصفوف الصحيحة كدفعة واحدة")


@login_required
@never_cache
@require_GET
def import_template(request):
    require_permission(request.user, Student, "add")
    response = HttpResponse(template_workbook(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="student-import-template.xlsx"'
    return response


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def import_upload(request):
    require_permission(request.user, Student, "add")
    form = ImportFileForm(request.POST if request.method == "POST" else None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            batch = preview_import(request.user, form.cleaned_data["file"])
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
        else:
            return redirect("import_preview", token=batch.token)
    return render(request, "students/import_upload.html", {"form": form})


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def import_preview(request, token):
    require_permission(request.user, Student, "add")
    batch = get_object_or_404(StudentImportBatch, token=token, actor=request.user)
    if not batch.committed_at and batch.expires_at <= timezone.now():
        StudentImportBatch.objects.filter(pk=batch.pk).update(payload=[])
        return HttpResponse("انتهت صلاحية المعاينة. ارفع الملف مجدداً.", status=410)
    form = ImportConfirmForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            result = commit_import(request.user, token)
        except ValidationError as exc:
            form.add_error(None, " ".join(exc.messages))
        except (IntegrityError, OperationalError):
            form.add_error(None, "تعذر استيراد الدفعة بسبب تعارض أو قفل قاعدة البيانات. لم تُحفظ صفوف جزئياً؛ أعد المعاينة.")
        else:
            messages.success(request, f"تم استيراد {result.imported_count} طالب بنجاح.")
            return redirect("record_list", resource="students")
    return render(request, "students/import_preview.html", {"batch": batch, "form": form, "invalid_count": sum(bool(row["errors"]) for row in batch.payload)})
