import hashlib
import os
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET


def instance_id():
    return hashlib.sha256(os.path.normcase(str(settings.BASE_DIR.resolve())).encode()).hexdigest()[:24]


@require_GET
def health(request):
    return JsonResponse({"application": "almuthanna-dormitory", "instance": instance_id()})
