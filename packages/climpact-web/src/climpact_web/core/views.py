from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

import climpact
import climpact_web


@require_safe
def home(request):
    return render(request, "core/home.html")


@never_cache
@require_safe
def healthz(request):
    """Health check for the load balancer and the ``climpact-web`` command: the app is up
    and its database answers. 200 with ``"status": "ok"``, else 503."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database = "ok"
    except Exception:  # any database failure means unhealthy
        database = "unavailable"
    healthy = database == "ok"
    return JsonResponse(
        {
            "status": "ok" if healthy else "error",
            "database": database,
            "version": climpact_web.__version__,
            "core_version": climpact.__version__,
        },
        status=200 if healthy else 503,
    )
