from django import forms
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, When, Value, CharField, Exists, OuterRef, Q, Count, Prefetch
from django.shortcuts import render, get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.accounts.policy import scope_queryset, require_permission, permitted
from apps.accommodations.models import Assignment
from apps.applications.models import Application
from apps.common.resources import label_for
from .models import Bed, Room, Building, Floor

STATES = {"available": "متاح", "reserved": "محجوز بانتظار الدخول", "occupied": "مشغول", "unavailable": "صيانة / خارج الخدمة"}


def mapped_beds(actor):
    active = Assignment.objects.filter(bed_id=OuterRef("pk"), ended_at__isnull=True)
    operational = Q(status="available", room__status="available", room__floor__is_active=True,
                    room__floor__building__is_active=True, room__floor__building__complex__is_active=True)
    return scope_queryset(actor, Bed.objects.all()).annotate(map_state=Case(
        When(~operational, then=Value("unavailable")),
        When(Exists(active.filter(checked_in_at__isnull=False)), then=Value("occupied")),
        When(Exists(active), then=Value("reserved")), default=Value("available"), output_field=CharField(),
    ))


class RoomMapFilters(forms.Form):
    building = forms.ModelChoiceField(label="البناية", queryset=Building.objects.none(), required=False)
    floor = forms.ModelChoiceField(label="الطابق", queryset=Floor.objects.none(), required=False)
    state = forms.ChoiceField(label="حالة السرير", choices=[("", "جميع الحالات"), *STATES.items()], required=False)
    application = forms.ModelChoiceField(label="طلب مقبول للتسكين السريع (اختياري)", queryset=Application.objects.none(), required=False)

    def __init__(self, actor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["building"].queryset = scope_queryset(actor, Building.objects.select_related("complex"))
        floors = scope_queryset(actor, Floor.objects.select_related("building__complex"))
        if self.data.get("building", "").isdigit():
            floors = floors.filter(building_id=self.data["building"])
        self.fields["floor"].queryset = floors
        self.fields["application"].queryset = scope_queryset(actor, Application.objects.filter(status="approved").select_related("enrollment__student", "enrollment__academic_year", "enrollment__department"))
        if not permitted(actor, Assignment, "add"):
            self.fields.pop("application")
        for name in ("building", "floor"):
            self.fields[name].label_from_instance = label_for
        if "application" in self.fields:
            self.fields["application"].label_from_instance = lambda item: label_for(item.enrollment)


@login_required
@never_cache
@require_GET
def room_map(request):
    require_permission(request.user, Room)
    require_permission(request.user, Bed)
    form = RoomMapFilters(request.user, request.GET)
    beds, rooms = mapped_beds(request.user), scope_queryset(request.user, Room.objects.select_related("floor__building__complex"))
    application = None
    if form.is_valid():
        if form.cleaned_data.get("building"):
            beds = beds.filter(room__floor__building=form.cleaned_data["building"])
            rooms = rooms.filter(floor__building=form.cleaned_data["building"])
        if form.cleaned_data.get("floor"):
            beds = beds.filter(room__floor=form.cleaned_data["floor"])
            rooms = rooms.filter(floor=form.cleaned_data["floor"])
        application = form.cleaned_data.get("application")
        if application:
            gender = application.enrollment.student.gender
            beds = beds.filter(room__floor__building__complex__gender=gender)
            rooms = rooms.filter(floor__building__complex__gender=gender)
    else:
        beds, rooms = beds.none(), rooms.none()
    counts = dict(beds.order_by().values_list("map_state").annotate(total=Count("pk")))
    if form.is_valid() and form.cleaned_data.get("state"):
        beds = beds.filter(map_state=form.cleaned_data["state"])
        rooms = rooms.filter(beds__pk__in=beds.values("pk")).distinct()
    rooms = rooms.prefetch_related(Prefetch("beds", queryset=beds.order_by("number"), to_attr="map_beds")).order_by("floor__building__name", "floor__number", "number")
    page = Paginator(rooms, 16).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "dormitories/map.html", {"form": form, "page": page, "query": query.urlencode(), "application": application,
        "legend": [(state, title, counts.get(state, 0)) for state, title in STATES.items()]})


class SuggestionFilters(forms.Form):
    building = forms.ModelChoiceField(label="البناية (اختياري)", queryset=Building.objects.none(), required=False)
    preference = forms.ChoiceField(label="ترتيب المقترحات", choices=[("space", "الغرف الأقل إشغالاً أولاً"), ("college", "زملاء الكلية ثم المساحة المتاحة")])


@login_required
@never_cache
@require_GET
def suggestions(request, pk):
    require_permission(request.user, Assignment, "add")
    require_permission(request.user, Bed)
    application = get_object_or_404(scope_queryset(request.user, Application.objects.select_related("enrollment__student", "enrollment__department__college")), pk=pk, status="approved")
    form = SuggestionFilters(request.GET or {"preference": "space"})
    form.fields["building"].queryset = scope_queryset(request.user, Building.objects.select_related("complex")).filter(complex__gender=application.enrollment.student.gender)
    form.fields["building"].label_from_instance = label_for
    beds = scope_queryset(request.user, Bed.objects.available().select_related("room__floor__building__complex")).filter(room__floor__building__complex__gender=application.enrollment.student.gender)
    if form.is_valid():
        if form.cleaned_data["building"]:
            beds = beds.filter(room__floor__building=form.cleaned_data["building"])
        same_college = scope_queryset(request.user, Assignment.objects.filter(ended_at__isnull=True,
            application__enrollment__department__college_id=application.enrollment.department.college_id)).values("pk")
        beds = beds.annotate(room_occupied=Count("room__beds__assignments", filter=Q(room__beds__assignments__ended_at__isnull=True, room__beds__assignments__pk__isnull=False), distinct=True),
                             college_peers=Count("room__beds__assignments", filter=Q(room__beds__assignments__pk__in=same_college), distinct=True))
        ordering = ["-college_peers"] if form.cleaned_data["preference"] == "college" else []
        beds = beds.order_by(*ordering, "room_occupied", "room__floor__building__name", "room__floor__number", "room__number", "number")
    else:
        beds = beds.none()
    return render(request, "dormitories/suggestions.html", {"application": application, "form": form, "beds": beds[:30]})
