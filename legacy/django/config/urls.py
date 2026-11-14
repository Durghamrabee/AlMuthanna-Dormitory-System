from django.conf import settings
from django.urls import include, path
from django.views.static import serve
from apps.common import views
from apps.common import workflows
from apps.reports import views as report_views
from apps.common import backup_views
from apps.dormitories import views as dormitory_views
from apps.students import import_views
from apps.reports import official_forms
from apps.common import alert_views
from apps.common.health import health

urlpatterns = [
    path("system/health/", health, name="health"),
    path("", views.home, name="home"),
    path("accounts/", include("apps.accounts.urls")),
    path("students/new/", views.student_edit, name="student_create"),
    path("students/import/", import_views.import_upload, name="import_upload"),
    path("students/import/template/", import_views.import_template, name="import_template"),
    path("students/import/<uuid:token>/", import_views.import_preview, name="import_preview"),
    path("students/<int:pk>/edit/", views.student_edit, name="student_edit"),
    path("students/<int:pk>/documents/new/", views.document_upload, name="document_upload"),
    path("documents/<int:pk>/download/", views.document_download, name="document_download"),
    path("documents/<int:pk>/photo/", views.document_photo, name="document_photo"),
    path("exports/students.xlsx", views.student_export, name="student_export"),
    path("reports/", report_views.report, name="reports"),
    path("alerts/", alert_views.alerts, name="alerts"),
    path("forms/settings/", official_forms.print_preferences, name="print_preferences"),
    path("forms/students/<int:pk>/<str:kind>/", official_forms.student_form, name="student_form_print"),
    path("forms/transfers/<int:pk>/", official_forms.transfer_form, name="transfer_form_print"),
    path("forms/checkouts/<int:pk>/", official_forms.checkout_form, name="checkout_form_print"),
    path("room-map/", dormitory_views.room_map, name="room_map"),
    path("applications/<int:pk>/suggestions/", dormitory_views.suggestions, name="bed_suggestions"),
    path("reports/<str:kind>/", report_views.report, name="report"),
    path("backups/", backup_views.backups, name="backups"),
    path("backups/<uuid:token>/download/", backup_views.backup_download, name="backup_download"),
    path("settings/", backup_views.preferences, name="preferences"),
    path("manage/<str:resource>/new/", workflows.resource_edit, name="resource_create"),
    path("manage/<str:resource>/<int:pk>/edit/", workflows.resource_edit, name="resource_edit"),
    path("applications/new/", workflows.application_create, name="application_create"),
    path("applications/<int:pk>/review/", workflows.application_transition, name="application_transition"),
    path("applications/<int:pk>/allocate/", workflows.application_allocate, name="application_allocate"),
    path("assignments/<int:pk>/<str:action>/", workflows.assignment_action, name="assignment_action"),
    path("maintenance/<int:pk>/status/", workflows.maintenance_action, name="maintenance_action"),
    path("records/<str:resource>/", views.record_list, name="record_list"),
    path("records/<str:resource>/<int:pk>/", views.record_detail, name="record_detail"),
]
# Offline local assets only. Private media and reset mail are never served.
if settings.LOCAL_HTTP:
    urlpatterns += [path("static/<path:path>", serve, {"document_root": settings.RESOURCE_DIR / "static"})]
