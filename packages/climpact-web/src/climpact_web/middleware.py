"""Request-level middleware for climpact-web."""

from django.conf import settings
from django.shortcuts import render


class UploadSizeLimitMiddleware:
    """Refuse requests whose body is larger than ``settings.MAX_UPLOAD_BYTES`` with a 413.

    Django limits only in-memory form data, not file uploads, so the overall limit is
    checked here from ``Content-Length`` before anything reads the body. The local server
    (waitress) is given the same limit for bodies sent without a length.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > settings.MAX_UPLOAD_BYTES:
            return render(
                request, "413.html", {"max_upload_mb": settings.MAX_UPLOAD_MB}, status=413
            )
        return self.get_response(request)
