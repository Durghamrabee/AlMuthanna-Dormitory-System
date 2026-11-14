"""Thin web handlers delegate state changes to transactional services."""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, OperationalError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.accounts.policy import permitted, require_permission, scope_queryset, REFERENCE_MODELS
from apps.applications.models import Application
from apps.applications.services import TRANSITIONS, create_application, transition_application
from apps.accommodations.models import Assignment
from apps.accommodations.services import allocate, check_in, check_out, transfer, renew
from apps.maintenance.models import MaintenanceRequest
from .forms import ApplicationForm, AllocationForm, AssignmentActionForm, TransitionForm, resource_form
from .resources import EDITABLE
from .services import save_resource, maintenance_transition, MAINTENANCE_TRANSITIONS

logger = logging.getLogger(__name__)


def run_form_action(form, callback):
    try:
        return callback()
    except ValidationError as exc:
        form.add_error(None, " ".join(exc.messages))
    except ObjectDoesNotExist:
        raise Http404("السجل غير متاح ضمن نطاقك الحالي.") from None
    except IntegrityError:
        form.add_error(None, "تعارض مع سجل موجود أو تخصيص متزامن. حدّث الصفحة وتحقق من البيانات.")
    except OperationalError:
        logger.error("A database operation could not complete; no form values were logged.")
        form.add_error(None, "تعذر إكمال العملية الآن. أغلق العمليات المتزامنة وحاول مجدداً.")
    return None


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def resource_edit(request, resource, pk=None):
    if resource not in EDITABLE:
        raise Http404
    model, title, _ = EDITABLE[resource]
    require_permission(request.user, model, "change" if pk else "add")
    if model._meta.label_lower in REFERENCE_MODELS and not request.user.is_superuser:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("إدارة البيانات المرجعية متاحة لمدير النظام فقط.")
    instance = get_object_or_404(scope_queryset(request.user, model.objects.all(), "change"), pk=pk) if pk else None
    initial = {}
    # Preselection remains subject to the form's scoped ModelChoiceField validation.
    for name in ("student", "complex", "building", "floor", "room", "academic_year"):
        if request.GET.get(name, "").isdigit():
            initial[name] = request.GET[name]
    form = resource_form(resource, request.user, request.POST if request.method == "POST" else None, instance, initial)
    if request.method == "POST" and form.is_valid():
        item = run_form_action(form, lambda: save_resource(request.user, resource, form))
        if item:
            messages.success(request, "تم حفظ البيانات بنجاح.")
            return redirect("record_detail", resource=resource, pk=item.pk)
    return render(request, "common/form.html", {"form": form, "title": ("تعديل — " if pk else "إضافة — ") + title})


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def application_create(request):
    require_permission(request.user, Application, "add")
    form = ApplicationForm(request.user, request.POST if request.method == "POST" else None, initial={"enrollment": request.GET.get("enrollment")})
    if request.method == "POST" and form.is_valid():
        item = run_form_action(form, lambda: create_application(request.user, form.cleaned_data["enrollment"].pk))
        if item:
            messages.success(request, "تم إنشاء مسودة الطلب. قدّمها بعد إكمال المستندات.")
            return redirect("record_detail", resource="applications", pk=item.pk)
    return render(request, "common/form.html", {"form": form, "title": "إنشاء طلب سكن"})


def application_choices(actor, item):
    choices = []
    for status in TRANSITIONS.get(item.status, ()):
        action = "decide" if status in {"approved", "rejected"} else "review" if status == "under_review" else "submit"
        if permitted(actor, Application, action) and permitted(actor, Application, "change"):
            choices.append((status, Application.Status(status).label))
    return choices


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def application_transition(request, pk):
    require_permission(request.user, Application, "change")
    item = get_object_or_404(scope_queryset(request.user, Application.objects.all(), "change"), pk=pk)
    form = TransitionForm(request.POST if request.method == "POST" else None)
    form.fields["status"].choices = application_choices(request.user, item)
    if request.method == "POST" and form.is_valid():
        result = run_form_action(form, lambda: transition_application(request.user, pk, form.cleaned_data["status"], form.cleaned_data["note"]))
        if result:
            messages.success(request, "تم تحديث حالة الطلب وحفظ القرار في السجل.")
            return redirect("record_detail", resource="applications", pk=pk)
    return render(request, "common/form.html", {"form": form, "title": "مراجعة طلب السكن"})


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def application_allocate(request, pk):
    require_permission(request.user, Assignment, "add")
    application = get_object_or_404(scope_queryset(request.user, Application.objects.select_related("enrollment__student")), pk=pk)
    form = AllocationForm(request.user, application.enrollment.student.gender, request.POST if request.method == "POST" else None, initial={"bed": request.GET.get("bed")})
    if request.method == "POST" and form.is_valid():
        item = run_form_action(form, lambda: allocate(request.user, pk, form.cleaned_data["bed"].pk))
        if item:
            messages.success(request, "تم حجز السرير. أكّد دخول الطالب عند وصوله.")
            return redirect("record_detail", resource="assignments", pk=item.pk)
    return render(request, "common/form.html", {"form": form, "title": "تخصيص سرير — " + application.enrollment.student.full_name})


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def assignment_action(request, pk, action):
    titles = {"checkin": "تأكيد دخول الطالب", "checkout": "إخلاء السكن", "transfer": "نقل الطالب إلى سرير آخر", "renew": "تجديد السكن لسنة أخرى"}
    if action not in titles:
        raise Http404
    require_permission(request.user, Assignment, "change")
    item = get_object_or_404(scope_queryset(request.user, Assignment.objects.select_related("student", "application__enrollment"), "change"), pk=pk)
    form = AssignmentActionForm(request.user, item, action, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        callbacks = {
            "checkin": lambda: check_in(request.user, pk),
            "checkout": lambda: check_out(request.user, pk, form.cleaned_data["reason"]),
            "transfer": lambda: transfer(request.user, pk, form.cleaned_data["bed"].pk, form.cleaned_data["reason"]),
            "renew": lambda: renew(request.user, pk, form.cleaned_data["application"].pk),
        }
        result = run_form_action(form, callbacks[action])
        if result:
            messages.success(request, "تم تنفيذ الإجراء وحفظ التاريخ السكني.")
            return redirect("record_detail", resource="assignments", pk=result.pk)
    return render(request, "common/form.html", {"form": form, "title": titles[action] + " — " + item.student.full_name})


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def maintenance_action(request, pk):
    require_permission(request.user, MaintenanceRequest, "change")
    item = get_object_or_404(scope_queryset(request.user, MaintenanceRequest.objects.all(), "change"), pk=pk)
    form = TransitionForm(request.POST if request.method == "POST" else None)
    form.fields["status"].choices = [(status, MaintenanceRequest.Status(status).label) for status in MAINTENANCE_TRANSITIONS.get(item.status, ())]
    if request.method == "POST" and form.is_valid():
        result = run_form_action(form, lambda: maintenance_transition(request.user, pk, form.cleaned_data["status"], form.cleaned_data["note"]))
        if result:
            messages.success(request, "تم تحديث حالة الصيانة.")
            return redirect("record_detail", resource="maintenance", pk=pk)
    return render(request, "common/form.html", {"form": form, "title": "تحديث حالة الصيانة"})
