from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from .alerts import alert_datasets, alert_settings


@login_required
@never_cache
@require_GET
def alerts(request):
    datasets = alert_datasets(request.user)
    category = request.GET.get("category", "documents")
    if category not in datasets:
        raise Http404
    title, records, resource = datasets[category]
    return render(request, "common/alerts.html", {"category": category, "title": title, "resource": resource,
        "categories": [(key, value[0], value[1].count()) for key, value in datasets.items()],
        "page": Paginator(records, 25).get_page(request.GET.get("page")), "alert_settings": alert_settings()})
