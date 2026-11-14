from django import forms
from django.contrib.auth import get_user_model
from apps.accounts.policy import scope_queryset
from apps.common.resources import EDITABLE, LABELS, label_for
from apps.applications.models import Application
from apps.academics.models import StudentEnrollment
from apps.dormitories.models import Bed


def scope_fields(form, actor):
    for name, field in form.fields.items():
        field.label = LABELS.get(name, field.label)
        if isinstance(field, forms.ModelChoiceField):
            if field.queryset.model == get_user_model():
                field.queryset = field.queryset.filter(is_active=True)
                if not actor.is_superuser:
                    field.queryset = field.queryset.filter(pk=actor.pk)
            else:
                field.queryset = scope_queryset(actor, field.queryset).select_related()
            field.label_from_instance = label_for


def resource_form(resource, actor, data=None, instance=None, initial=None):
    model, _, fields = EDITABLE[resource]
    widgets = {name: forms.DateInput(attrs={"type": "date"}) for name in fields if name.endswith("_on")}
    form_class = forms.modelform_factory(model, fields=fields, widgets=widgets)
    form = form_class(data, instance=instance, initial=initial)
    scope_fields(form, actor)
    if resource == "maintenance":
        for name in ("building", "room", "bed"):
            form.fields[name].help_text = "حدد موقعاً واحداً فقط: بناية أو غرفة أو سرير."
    return form


class ApplicationForm(forms.Form):
    enrollment = forms.ModelChoiceField(label="التسجيل الدراسي", queryset=StudentEnrollment.objects.none())

    def __init__(self, actor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["enrollment"].queryset = scope_queryset(actor, StudentEnrollment.objects.select_related("student", "academic_year", "department")).exclude(applications__isnull=False)
        self.fields["enrollment"].label_from_instance = label_for


class TransitionForm(forms.Form):
    status = forms.ChoiceField(label="الإجراء", choices=())
    note = forms.CharField(label="سبب القرار / الملاحظات", widget=forms.Textarea, max_length=2000, required=False)
    confirm = forms.BooleanField(label="أؤكد تنفيذ هذا الإجراء")


class AllocationForm(forms.Form):
    bed = forms.ModelChoiceField(label="السرير المتاح", queryset=Bed.objects.none())
    confirm = forms.BooleanField(label="أؤكد حجز السرير للطالب")

    def __init__(self, actor, gender, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bed"].queryset = scope_queryset(actor, Bed.objects.available().select_related("room__floor__building__complex")).filter(room__floor__building__complex__gender=gender)
        self.fields["bed"].label_from_instance = label_for


class AssignmentActionForm(forms.Form):
    reason = forms.CharField(label="السبب", max_length=500, widget=forms.Textarea, required=False)
    bed = forms.ModelChoiceField(label="السرير الجديد", queryset=Bed.objects.none(), required=False)
    application = forms.ModelChoiceField(label="طلب التجديد المقبول للسنة الأخرى", queryset=Application.objects.none(), required=False)
    confirm = forms.BooleanField(label="أؤكد تنفيذ الإجراء وحفظه في السجل")

    def __init__(self, actor, assignment, action, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if action in {"transfer", "checkout"}:
            self.fields["reason"].required = True
        else:
            self.fields.pop("reason")
        if action == "transfer":
            self.fields["bed"].required = True
            self.fields["bed"].queryset = scope_queryset(actor, Bed.objects.available()).filter(room__floor__building__complex__gender=assignment.student.gender)
            self.fields["bed"].label_from_instance = label_for
        else:
            self.fields.pop("bed")
        if action == "renew":
            self.fields["application"].required = True
            self.fields["application"].queryset = scope_queryset(actor, Application.objects.filter(status="approved", enrollment__student_id=assignment.student_id).select_related("enrollment__student", "enrollment__academic_year", "enrollment__department")).exclude(enrollment__academic_year_id=assignment.application.enrollment.academic_year_id)
            self.fields["application"].label_from_instance = lambda item: label_for(item.enrollment)
        else:
            self.fields.pop("application")
