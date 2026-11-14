"""Editable administrative forms; no official university policy or seal is invented."""
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.models import SystemSetting
from apps.accounts.policy import require_account_admin, require_permission, scope_queryset
from apps.academics.models import StudentEnrollment
from apps.accommodations.models import Assignment, AccommodationTransfer
from apps.audit.services import record_event
from apps.students.models import Student
from apps.common.resources import label_for
from .pdf import render_pdf

DEFAULTS = {
    "housing": ("استمارة السكن الجامعي", "تُثبت بيانات الطالب وموقع السكن المبينان في هذه الاستمارة بعد مراجعتها من الموظف المخول. تُستكمل حقول التوقيع والاعتماد أدناه."),
    "pledge": ("تعهد بصحة البيانات", "أقر بأن البيانات المثبتة في هذه الاستمارة صحيحة بحسب إفادتي، وألتزم بإبلاغ إدارة السكن عند تغير بيانات الاتصال أو عنوان السكن."),
    "transfer": ("أمر نقل سكن", "تُعرض حركة النقل المسجلة في النظام أدناه على الموظف المخول لاعتمادها واستكمال التواقيع. يبقى سجل الموقع السابق محفوظاً."),
    "checkout": ("استمارة إخلاء السكن", "تُثبت واقعة إنهاء تخصيص السكن المسجلة أدناه، وتُستكمل ملاحظات الاستلام والتواقيع من الموظف المخول."),
}


def form_preferences():
    stored = SystemSetting.objects.filter(key="print_templates").values_list("value", flat=True).first()
    values = {"university": "جامعة المثنى", "office": "إدارة الأقسام الداخلية"}
    if isinstance(stored, dict):
        values.update({key: value for key, value in stored.items() if isinstance(value, str)})
    for kind, (title, body) in DEFAULTS.items():
        values.setdefault(kind + "_title", title)
        values.setdefault(kind + "_body", body)
    return values


class PrintPreferences(forms.Form):
    university = forms.CharField(label="اسم الجامعة في الترويسة", max_length=150)
    office = forms.CharField(label="اسم الجهة الإدارية", max_length=150)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for kind, (title, _) in DEFAULTS.items():
            self.fields[kind + "_title"] = forms.CharField(label="عنوان " + title, max_length=150)
            self.fields[kind + "_body"] = forms.CharField(label="نص " + title, max_length=4000, widget=forms.Textarea)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def print_preferences(request):
    require_account_admin(request.user)
    form = PrintPreferences(request.POST if request.method == "POST" else None, initial=form_preferences())
    if request.method == "POST" and form.is_valid():
        setting, _ = SystemSetting.objects.update_or_create(key="print_templates", defaults={"value": form.cleaned_data, "description": "ترويسة ونصوص النماذج الإدارية القابلة للتعديل", "updated_by": request.user})
        record_event("settings.updated", actor=request.user, target=setting, fields=("print_templates",))
        messages.success(request, "تم حفظ ترويسة ونصوص النماذج. الصيغ العامة قابلة لاعتماد وتعديل الإدارة وليست لائحة جامعية مفترضة.")
        return redirect("print_preferences")
    return render(request, "common/form.html", {"title": "تخصيص نماذج الطباعة والترويسة", "form": form})


def output_form(request, student, kind, assignment=None, movement=None):
    require_permission(request.user, Student)
    student = get_object_or_404(scope_queryset(request.user, Student.objects.all()), pk=student.pk)
    preferences = form_preferences()
    enrollment = assignment.application.enrollment if assignment else scope_queryset(request.user, StudentEnrollment.objects.filter(student=student)).select_related("academic_year", "department__college").order_by("-academic_year__starts_on").first()
    rows = [("الاسم الكامل", student.full_name), ("الرقم الجامعي", student.university_number), ("الجنس", student.get_gender_display()),
            ("الهاتف", student.phone), ("المحافظة والقضاء", f"{student.governorate} / {student.district}")]
    if enrollment:
        rows += [("الكلية والقسم", f"{enrollment.department.college.name} / {enrollment.department.name}"),
                 ("السنة والمرحلة", f"{enrollment.academic_year.name} / {enrollment.stage}")]
    if assignment:
        rows += [("موقع السكن", label_for(assignment.bed)), ("تاريخ التخصيص", timezone.localtime(assignment.allocated_at).strftime("%Y-%m-%d %H:%M"))]
    if movement:
        rows += [("الموقع السابق", label_for(movement.previous_assignment.bed)), ("الموقع الجديد", label_for(movement.new_assignment.bed)), ("سبب النقل", movement.reason)]
    if kind == "checkout":
        rows += [("تاريخ إنهاء السكن", timezone.localtime(assignment.ended_at).strftime("%Y-%m-%d %H:%M")), ("السبب", assignment.end_reason)]
    context = {"title": preferences[kind + "_title"], "body_text": preferences[kind + "_body"], "university": preferences["university"],
               "office": preferences["office"], "student": student, "rows": rows, "generated_at": timezone.localtime(),
               "reference": f"{kind.upper()}-{movement.pk if movement else assignment.pk if assignment else student.pk}",
               "font_uri": (settings.RESOURCE_DIR / "static/fonts/Cairo.ttf").as_uri() if request.GET.get("format") == "pdf" else static("fonts/Cairo.ttf")}
    html = render_to_string("reports/administrative_form.html", context, request=request)
    if request.GET.get("format") == "pdf":
        try:
            result = render_pdf(html)
        except ValidationError as exc:
            return render(request, "reports/form_error.html", {"errors": exc.messages}, status=503)
        record_event("form.printed", actor=request.user, target=assignment or student)
        response = HttpResponse(result, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{kind}-{student.pk}.pdf"'
        return response
    return HttpResponse(html)


@login_required
@never_cache
@require_GET
def student_form(request, pk, kind):
    if kind not in {"housing", "pledge"}:
        raise Http404
    require_permission(request.user, Student)
    student = get_object_or_404(scope_queryset(request.user, Student.objects.all()), pk=pk)
    assignments = scope_queryset(request.user, Assignment.objects.filter(student=student)).select_related("bed__room__floor__building__complex", "application__enrollment__department__college", "application__enrollment__academic_year")
    if request.GET.get("assignment"):
        if not request.GET["assignment"].isdigit():
            raise Http404
        assignment = get_object_or_404(assignments, pk=request.GET["assignment"])
    else:
        assignment = assignments.filter(ended_at__isnull=True).first()
    return output_form(request, student, kind, assignment)


@login_required
@never_cache
@require_GET
def transfer_form(request, pk):
    require_permission(request.user, AccommodationTransfer)
    movement = get_object_or_404(scope_queryset(request.user, AccommodationTransfer.objects.select_related("previous_assignment__bed__room__floor__building__complex", "new_assignment__bed__room__floor__building__complex", "new_assignment__student")), pk=pk)
    return output_form(request, movement.new_assignment.student, "transfer", movement.new_assignment, movement)


@login_required
@never_cache
@require_GET
def checkout_form(request, pk):
    require_permission(request.user, Assignment)
    assignment = get_object_or_404(scope_queryset(request.user, Assignment.objects.filter(ended_at__isnull=False, outgoing_transfer__isnull=True, renewal__isnull=True)).select_related("student", "bed__room__floor__building__complex"), pk=pk)
    return output_form(request, assignment.student, "checkout", assignment)
