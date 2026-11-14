from django import forms
from django.db.models import Q

from apps.accounts.policy import scope_queryset
from apps.academics.models import College, Department, AcademicYear
from apps.dormitories.models import DormitoryComplex, Building, Floor, Room
from apps.common.resources import label_for

PATHS = {
    "students": {"gender": "gender", "governorate": "governorate", "college": "enrollments__department__college_id", "department": "enrollments__department_id", "year": "enrollments__academic_year_id"},
    "enrollments": {"gender": "student__gender", "governorate": "student__governorate", "college": "department__college_id", "department": "department_id", "year": "academic_year_id"},
    "applications": {"gender": "enrollment__student__gender", "governorate": "enrollment__student__governorate", "college": "enrollment__department__college_id", "department": "enrollment__department_id", "year": "enrollment__academic_year_id", "status": "status", "date": "created_at__date"},
    "assignments": {"gender": "student__gender", "governorate": "student__governorate", "college": "application__enrollment__department__college_id", "department": "application__enrollment__department_id", "year": "application__enrollment__academic_year_id", "complex": "bed__room__floor__building__complex_id", "building": "bed__room__floor__building_id", "date": "allocated_at__date"},
    "complexes": {"gender": "gender"},
    "buildings": {"gender": "complex__gender", "complex": "complex_id"},
    "floors": {"gender": "building__complex__gender", "complex": "building__complex_id", "building": "building_id"},
    "rooms": {"gender": "floor__building__complex__gender", "complex": "floor__building__complex_id", "building": "floor__building_id", "floor": "floor_id", "status": "status"},
    "beds": {"gender": "room__floor__building__complex__gender", "complex": "room__floor__building__complex_id", "building": "room__floor__building_id", "room": "room_id", "status": "status"},
    "violations": {"gender": "student__gender", "governorate": "student__governorate", "date": "occurred_on"},
    "maintenance": {"status": "status", "date": "created_at__date"},
}


class RecordFilters(forms.Form):
    q = forms.CharField(label="بحث", max_length=100, required=False)
    gender = forms.ChoiceField(label="الجنس", choices=[("", "الكل"), ("male", "طلاب"), ("female", "طالبات")], required=False)
    governorate = forms.CharField(label="المحافظة", max_length=100, required=False)
    college = forms.ModelChoiceField(label="الكلية", queryset=College.objects.none(), required=False)
    department = forms.ModelChoiceField(label="القسم العلمي", queryset=Department.objects.none(), required=False)
    year = forms.ModelChoiceField(label="السنة الدراسية", queryset=AcademicYear.objects.none(), required=False)
    complex = forms.ModelChoiceField(label="المجمع", queryset=DormitoryComplex.objects.none(), required=False)
    building = forms.ModelChoiceField(label="البناية", queryset=Building.objects.none(), required=False)
    floor = forms.ModelChoiceField(label="الطابق", queryset=Floor.objects.none(), required=False)
    room = forms.ModelChoiceField(label="الغرفة", queryset=Room.objects.none(), required=False)
    status = forms.ChoiceField(label="الحالة", choices=(), required=False)
    start = forms.DateField(label="من تاريخ", widget=forms.DateInput(attrs={"type": "date"}), required=False)
    end = forms.DateField(label="إلى تاريخ", widget=forms.DateInput(attrs={"type": "date"}), required=False)

    def __init__(self, actor, resource, data=None):
        super().__init__(data)
        self.paths = PATHS.get(resource, {})
        allowed = set(self.paths) | {"q"}
        if "date" in allowed:
            allowed |= {"start", "end"}
        for name in list(self.fields):
            if name not in allowed:
                self.fields.pop(name)
        for field in self.fields.values():
            if isinstance(field, forms.ModelChoiceField):
                field.queryset = scope_queryset(actor, field.queryset.model.objects.all()).select_related()
                field.label_from_instance = label_for
        if "status" in self.fields:
            from apps.common.views import RESOURCES
            self.fields["status"].choices = [("", "الكل"), *RESOURCES[resource][0]._meta.get_field("status").choices]

    def clean(self):
        values = super().clean()
        if values.get("start") and values.get("end") and values["start"] > values["end"]:
            raise forms.ValidationError("تاريخ البداية يجب أن يسبق تاريخ النهاية.")
        return values

    def apply(self, queryset):
        if not self.is_valid():
            return queryset.none()
        filters = {}
        for name, path in self.paths.items():
            if name == "date":
                for key, lookup in (("start", "gte"), ("end", "lte")):
                    if self.cleaned_data.get(key):
                        filters[f"{path}__{lookup}"] = self.cleaned_data[key]
            elif self.cleaned_data.get(name):
                value = self.cleaned_data[name]
                filters[path] = getattr(value, "pk", value)
        queryset = queryset.filter(**filters)
        search = self.cleaned_data.get("q", "").strip()
        if search:
            from django.db.models import CharField, TextField
            rule = Q()
            for field in queryset.model._meta.fields:
                if isinstance(field, (CharField, TextField)) and not field.is_relation:
                    rule |= Q(**{f"{field.name}__icontains": search})
            related_paths = {"academics.studentenrollment": "student__full_name", "applications.application": "enrollment__student__full_name", "accommodations.assignment": "student__full_name", "violations.violation": "student__full_name"}
            if queryset.model._meta.label_lower in related_paths:
                rule |= Q(**{related_paths[queryset.model._meta.label_lower] + "__icontains": search})
            if rule:
                queryset = queryset.filter(rule)
        return queryset.distinct()
