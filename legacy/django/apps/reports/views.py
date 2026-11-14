from io import BytesIO

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.templatetags.static import static
from openpyxl import Workbook
from openpyxl.styles import Font

from apps.audit.services import record_event
from .data import REPORTS, report_data
from .filters import RecordFilters
from .pdf import render_pdf


@login_required
@never_cache
@require_GET
def report(request, kind="students"):
    if kind not in REPORTS:
        raise Http404
    output = request.GET.get("format", "html")
    permission = "export_reports" if output in {"xlsx", "pdf"} else "view_reports"
    if not request.user.has_perm("accounts." + permission):
        raise PermissionDenied
    title, resource, _ = REPORTS[kind]
    filters = RecordFilters(request.user, resource, request.GET)
    headers, rows = [], []
    context = {"title": title, "kind": kind, "reports": REPORTS, "filters": filters, "generated_at": timezone.localtime(),
               "font_uri": (settings.RESOURCE_DIR / "static/fonts/Cairo.ttf").as_uri()}
    try:
        headers, rows = report_data(request.user, kind, filters, limit=2000 if output == "pdf" else 20000)
        if output == "xlsx" and filters.is_valid():
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = title[:31]
            sheet.sheet_view.rightToLeft = True
            sheet.append(headers)
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            for row in rows:
                sheet.append(row)
                for cell in sheet[sheet.max_row]:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
            sheet.freeze_panes, sheet.auto_filter.ref = "A2", sheet.dimensions
            stream = BytesIO()
            workbook.save(stream)
            record_event("report.exported", actor=request.user, fields=(kind,))
            response = HttpResponse(stream.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            response["Content-Disposition"] = f'attachment; filename="{kind}.xlsx"'
            return response
        context.update(headers=headers, rows=rows)
        if output in {"pdf", "print"} and filters.is_valid():
            if output == "print":
                context["font_uri"] = static("fonts/Cairo.ttf")
            html = render_to_string("reports/print.html", context, request=request)
            if output == "print":
                return HttpResponse(html)
            data = render_pdf(html)
            record_event("report.exported", actor=request.user, fields=(kind,))
            response = HttpResponse(data, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="{kind}.pdf"'
            return response
    except ValidationError as exc:
        filters.add_error(None, " ".join(exc.messages))
    query = request.GET.copy()
    query.pop("format", None)
    query.pop("page", None)
    context.update(headers=headers, rows=rows, page=Paginator(rows, 50).get_page(request.GET.get("page")), query=query.urlencode())
    return render(request, "reports/list.html", context)
