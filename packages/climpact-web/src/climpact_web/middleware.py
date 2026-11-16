"""Request-level middleware for climpact-web."""

import logging
from pathlib import Path

from django.conf import settings
from django.middleware import csp
from django.middleware.gzip import GZipMiddleware
from django.shortcuts import render
from django.utils.cache import patch_cache_control
from whitenoise.middleware import WhiteNoiseMiddleware

from climpact_web.core.limits import Refused, client_ip

limits_logger = logging.getLogger("climpact_web.limits")

# Responses worth compressing: pages, htmx fragments, chart data, CSV (#82).
COMPRESSIBLE_TYPES = ("text/", "application/json", "image/svg+xml")


class ContentSecurityPolicyMiddleware(csp.ContentSecurityPolicyMiddleware):
    """Django's CSP middleware, with the nonce in every HTML page's header (#164).

    Django makes the nonce only when something reads it (a template's ``csp_nonce``) and
    otherwise leaves ``CSP.NONCE`` out of the header. No template uses it, but Cloudflare
    copies the header's nonce to the scripts its edge adds to each page (JavaScript
    detections), so it must always be there. Each page gets its own: pages are never
    cached (``Cache-Control: private`` or ``never_cache``). Other answers (static files,
    downloads, JSON) keep Django's behaviour; a CSP header does nothing for them.
    """

    def process_response(self, request, response):
        nonce = csp.get_nonce(request)
        if nonce is not None and response.get("Content-Type", "").startswith("text/html"):
            str(nonce)  # generates it
        return super().process_response(request, response)


class StaticFilesMiddleware(WhiteNoiseMiddleware):
    """WhiteNoise, without its warning when ``STATIC_ROOT`` does not exist yet: in local
    mode the folder is made by ``collectstatic`` when ``climpact-web`` starts, and until
    then the finders serve every file from the package."""

    def add_files(self, root, prefix=None):
        if Path(root).is_dir():
            super().add_files(root, prefix)


class PrivateCacheMiddleware:
    """Mark every answer that says nothing about caching as ``Cache-Control: private``.

    Cloudflare caches some answers by file extension alone (``.csv``, ``.png``, ``.pdf``,
    ``.zip``, ...) when the origin sends no ``Cache-Control``, and it ignores ``Vary:
    Cookie``. The job downloads (``/jobs/<id>/files/...``) and the station's
    ``series.csv`` belong to one visitor's session, so a shared cache must never keep
    them. Answers that set their own ``Cache-Control`` keep it. It sits below WhiteNoise,
    so static files (hashed names, cached for a year) never pass through it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not response.has_header("Cache-Control"):
            patch_cache_control(response, private=True)
        return response


class CompressionMiddleware(GZipMiddleware):
    """Gzip pages, htmx fragments and other text answers for browsers that accept it.

    Django's own middleware, limited to text: file downloads (zips, netCDF, PNG) are
    already compressed or streamed, and static files come precompressed from WhiteNoise,
    which answers before this middleware runs. Django's middleware pads each answer with
    random bytes against BREACH, and the CSRF token is masked afresh on every page.
    """

    def process_response(self, request, response):
        if response.streaming or not response.get("Content-Type", "").startswith(
            COMPRESSIBLE_TYPES
        ):
            return response
        return super().process_response(request, response)


def upload_limit(path: str) -> tuple[int, int]:
    """The largest body accepted for a request to ``path``: ``(bytes, MB)``. The gridded
    pages (#85), which upload netCDF files, may send up to GRIDDED_MAX_UPLOAD_BYTES."""
    if settings.GRIDDED_ENABLED and path.startswith("/gridded/"):
        return settings.GRIDDED_MAX_UPLOAD_BYTES, settings.GRIDDED_MAX_UPLOAD_MB
    return settings.MAX_UPLOAD_BYTES, settings.MAX_UPLOAD_MB


class UploadSizeLimitMiddleware:
    """Refuse requests whose body is larger than ``settings.MAX_UPLOAD_BYTES`` with a 413
    (``GRIDDED_MAX_UPLOAD_BYTES`` for the gridded uploads).

    Django limits only in-memory form data, not file uploads, so the overall limit is
    checked here from ``Content-Length`` before anything reads the body. The local server
    (waitress) is given the larger of the two limits for bodies sent without a length.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        limit, limit_mb = upload_limit(request.path_info)
        if length > limit:
            return render(request, "413.html", {"max_upload_mb": limit_mb}, status=413)
        return self.get_response(request)


class RefusalMiddleware:
    """Answer a request refused by the hosted site's limits (:mod:`climpact_web.core.limits`)
    with a page saying why in plain language, and log the refusal with the client's address
    and the reason, so the Cloudflare rules can be tuned from the logs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, Refused):
            return None
        limits_logger.warning(
            "Refused %s %s from %s: %s",
            request.method,
            request.path,
            client_ip(request),
            exception.reason,
        )
        response = render(
            request, "refused.html", {"message": exception.message}, status=exception.status
        )
        if exception.retry_after:
            response["Retry-After"] = str(exception.retry_after)
        return response
