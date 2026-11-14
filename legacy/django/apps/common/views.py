from io import BytesIO
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.accounts.policy import require_permission, scope_queryset
from apps.audit.models import AuditLog
from apps.audit.services import record_event
from apps.applications.models import Application
from apps.accommodations.models import Assignment
from apps.dormitories.models import DormitoryComplex, Building, Floor, Room, Bed
from apps.maintenance.models import MaintenanceRequest
from apps.students.models import Student, StudentDocument
from apps.students.forms import StudentForm, DocumentForm
from apps.students.services import save_student
from apps.violations.models import Violation
from .resources import EDITABLE, LABELS, label_for
from apps.accounts.policy import permitted, REFERENCE_MODELS

RESOURCES = {
    "students": (Student, "الطلبة"), "complexes": (DormitoryComplex, "المجمعات"),
    "buildings": (Building, "البنايات"), "floors": (Floor, "الطوابق"),
    "rooms": (Room, "الغرف"), "beds": (Bed, "الأسرّة"),
    "applications": (Application, "طلبات السكن"), "assignments": (Assignment, "التخصيصات"),
    "violations": (Violation, "المخالفات"), "maintenance": (MaintenanceRequest, "الصيانة"),
    "audit": (AuditLog, "سجل التدقيق"),
}
RESOURCES.update({key: (model, title) for key, (model, title, _) in EDITABLE.items()})


def resource_info(resource):
    try:
        return RESOURCES[resource]
    except KeyError:
        raise Http404 from None


def object_title(item):
    if isinstance(item, AuditLog):
        return item.get_action_display()
    if isinstance(item, Application):
        return label_for(item.enrollment)
    if isinstance(item, Assignment):
        return f"{item.student.full_name} — {label_for(item.bed)}"
    if isinstance(item, Violation):
        return f"{item.student.full_name} — {item.violation_type.name}"
    if isinstance(item, MaintenanceRequest):
        return f"{item.category} — {label_for(item.building or item.room or item.bed)}"
    if isinstance(item, (Building, Floor, Room, Bed)):
        return label_for(item)
    for field in ("full_name", "name", "number"):
        value = getattr(item, field, None)
        if value:
            return value
    return label_for(item)


@login_required
@never_cache
def home(request):
    from apps.reports.dashboard import dashboard_context
    links = [(resource, title) for resource, (model, title) in RESOURCES.items()
             if request.user.has_perm(f"{model._meta.app_label}.view_{model._meta.model_name}")]
    context = dashboard_context(request.user)
    if request.user.is_superuser:
        from .backup_views import backup_status
        context.update(backup_status())
    context["links"] = links
    return render(request, "common/home.html", context)


@login_required
@never_cache
def record_list(request, resource):
    model, title = resource_info(resource)
    require_permission(request.user, model)
    records = scope_queryset(request.user, model.objects.all()).order_by("pk")
    from apps.reports.filters import RecordFilters
    filters = RecordFilters(request.user, resource, request.GET)
    records = filters.apply(records)
    if resource in {"assignments", "beds", "rooms", "floors", "buildings", "applications", "enrollments", "violations", "maintenance"}:
        records = records.select_related()
    if resource == "maintenance":
        records = records.select_related("building__complex", "room__floor__building__complex", "bed__room__floor__building__complex")
    page = Paginator(records, 25).get_page(request.GET.get("page"))
    rows = [(item.pk, object_title(item)) for item in page]
    query = request.GET.copy()
    query.pop("page", None)
    can_manage = request.user.is_superuser or model._meta.label_lower not in REFERENCE_MODELS
    return render(request, "common/list.html", {"resource": resource, "title": title, "rows": rows, "page": page, "filters": filters, "query": query.urlencode(), "can_create": resource in EDITABLE and can_manage and permitted(request.user, model, "add"), "search": request.GET.get("q", "")})


@login_required
@never_cache
def record_detail(request, resource, pk):
    model, title = resource_info(resource)
    require_permission(request.user, model)
    item = get_object_or_404(scope_queryset(request.user, model.objects.all()), pk=pk)
    context = {"resource": resource, "title": title, "item": item, "item_title": object_title(item)}
    if model == Student:
        context["documents"] = scope_queryset(request.user, StudentDocument.objects.filter(student=item)).select_related("document_type")
        context["photograph"] = context["documents"].filter(document_type__is_photograph=True).order_by("-created_at").first()
        from apps.academics.models import StudentEnrollment
        context["enrollments"] = scope_queryset(request.user, StudentEnrollment.objects.filter(student=item)).select_related("academic_year", "department__college")
        context["applications"] = scope_queryset(request.user, Application.objects.filter(enrollment__student=item)).select_related("enrollment__academic_year")
        context["accommodation_history"] = scope_queryset(request.user, Assignment.objects.filter(student=item)).select_related("bed__room__floor__building__complex").order_by("-allocated_at")
        context["violations"] = scope_queryset(request.user, Violation.objects.filter(student=item)).select_related("violation_type")
    if model == Application:
        from .workflows import application_choices
        context["can_transition"] = bool(application_choices(request.user, item))
        context["application_history"] = scope_queryset(request.user, item.status_history.all()).select_related("changed_by")
    if model == MaintenanceRequest:
        context["maintenance_history"] = scope_queryset(request.user, item.status_history.all()).select_related("changed_by")
    if model == Bed:
        context["occupants"] = scope_queryset(request.user, Assignment.objects.filter(bed=item, ended_at__isnull=True)).select_related("student")
    if model == Room:
        context["room_beds"] = scope_queryset(request.user, Bed.objects.filter(room=item)).order_by("number")
        context["occupants"] = scope_queryset(request.user, Assignment.objects.filter(bed__room=item, ended_at__isnull=True)).select_related("student", "bed")
    if model == Assignment:
        from apps.accommodations.models import AccommodationTransfer
        context["print_transfer"] = scope_queryset(request.user, AccommodationTransfer.objects.filter(previous_assignment=item)).first()
        context["can_print_checkout"] = bool(item.ended_at and not AccommodationTransfer.objects.filter(previous_assignment=item).exists() and not Assignment.objects.filter(renewed_from=item).exists())
    context["can_edit"] = resource in EDITABLE and (request.user.is_superuser or model._meta.label_lower not in REFERENCE_MODELS) and permitted(request.user, model, "change")
    hierarchy = {"complexes": ("buildings", Building, "complex"), "buildings": ("floors", Floor, "building"), "floors": ("rooms", Room, "floor")}
    if resource in hierarchy:
        child_resource, child_model, parent = hierarchy[resource]
        children = scope_queryset(request.user, child_model.objects.filter(**{parent: item})).select_related()
        context.update(child_resource=child_resource, child_title=RESOURCES[child_resource][1],
            children=[(child.pk, label_for(child)) for child in children.order_by("pk")[:25]], child_count=children.count(),
            child_filter=f"{parent}={item.pk}", can_create_child=permitted(request.user, child_model, "add"))
    detail_rows = []
    if resource not in {"students", "audit"}:
        for field in model._meta.fields:
            if field.name in {"id", "active_student_key", "active_bed_key"}:
                continue
            value = getattr(item, field.name)
            if field.is_relation and value is not None:
                value = label_for(value)
            elif field.choices:
                value = getattr(item, f"get_{field.name}_display")()
            elif isinstance(value, bool):
                value = "نعم" if value else "لا"
            detail_rows.append((LABELS.get(field.name, field.verbose_name), value))
    context["detail_rows"] = detail_rows
    return render(request, "common/detail.html", context)


@login_required
@require_http_methods(["GET", "POST"])
@never_cache
def student_edit(request, pk=None):
    action = "change" if pk else "add"
    require_permission(request.user, Student, action)
    target = get_object_or_404(scope_queryset(request.user, Student.objects.all(), action), pk=pk) if pk else None
    form = StudentForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        try:
            student = save_student(request.user, form, target)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("record_detail", resource="students", pk=student.pk)
    return render(request, "common/form.html", {"form": form, "title": "تعديل بيانات الطالب" if pk else "تسجيل طالب"})


@login_required
@require_http_methods(["GET", "POST"])
@never_cache
def document_upload(request, pk):
    require_permission(request.user, StudentDocument, "add")
    require_permission(request.user, Student)
    student = get_object_or_404(scope_queryset(request.user, Student.objects.all()), pk=pk)
    document = StudentDocument(student=student, uploaded_by=request.user)
    form = DocumentForm(request.POST or None, request.FILES or None, instance=document)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                # Recheck authorization inside the write transaction.
                if not scope_queryset(request.user, Student.objects.filter(pk=pk)).exists():
                    raise PermissionDenied
                document = form.save()
                record_event("document.uploaded", actor=request.user, target=document)
        except Exception:
            # File storage is not transactional: remove this new upload after rollback.
            if document.file and document.file._committed:
                document.file.delete(save=False)
            raise
        return redirect("record_detail", resource="students", pk=pk)
    return render(request, "common/form.html", {"form": form, "title": "رفع مستند الطالب"})


@login_required
@never_cache
def document_download(request, pk):
    require_permission(request.user, StudentDocument)
    document = get_object_or_404(scope_queryset(request.user, StudentDocument.objects.all()), pk=pk)
    if not document.file:
        raise Http404
    try:
        opened = document.file.open("rb")
    except FileNotFoundError:
        raise Http404("المستند غير متوفر.") from None
    response = FileResponse(opened, as_attachment=True, filename=f"document-{document.pk}{Path(document.file.name).suffix}")
    response["Content-Type"] = "application/octet-stream"
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    try:
        record_event("document.downloaded", actor=request.user, target=document)
    except Exception:
        response.close()
        raise
    return response


@login_required
@never_cache
def student_export(request):
    from openpyxl import Workbook
    require_permission(request.user, Student, "export")
    require_permission(request.user, Student)
    from apps.reports.filters import RecordFilters
    filters = RecordFilters(request.user, "students", request.GET)
    if not filters.is_valid():
        return HttpResponse("عوامل التصفية غير صالحة.", status=400)
    records = filters.apply(scope_queryset(request.user, Student.objects.all()))
    if records.count() > 20000:
        return HttpResponse("النتائج تتجاوز 20000 سجل. ضيّق التصفية ثم أعد التصدير.", status=400)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "الطلبة"
    sheet.sheet_view.rightToLeft = True
    sheet.append(["الرقم الجامعي", "الاسم الكامل", "الجنس", "المحافظة"])
    for student in records.iterator(chunk_size=500):
        sheet.append([student.university_number, student.full_name, student.get_gender_display(), student.governorate])
        # Treat user text as text even if it starts with '=' (spreadsheet injection).
        for cell in sheet[sheet.max_row]:
            cell.data_type = "s"
    output = BytesIO()
    workbook.save(output)
    record_event("student.exported", actor=request.user)
    response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="students.xlsx"'
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@never_cache
def document_photo(request, pk):
    from PIL import Image, ImageOps
    require_permission(request.user, StudentDocument)
    document = get_object_or_404(scope_queryset(request.user, StudentDocument.objects.filter(document_type__is_photograph=True)), pk=pk)
    try:
        with document.file.open("rb") as source, Image.open(source) as image:
            if image.format not in {"JPEG", "PNG"} or image.width * image.height > 25_000_000:
                raise Http404
            image = ImageOps.exif_transpose(image)
            image.thumbnail((256, 256))
            stream = BytesIO()
            image.convert("RGB").save(stream, format="PNG")
    except (OSError, ValueError, Image.DecompressionBombError):
        raise Http404("الصورة غير متوفرة.") from None
    response = HttpResponse(stream.getvalue(), content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    return response
