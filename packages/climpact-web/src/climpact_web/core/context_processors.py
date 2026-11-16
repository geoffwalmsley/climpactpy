from django.conf import settings

import climpact_web
from climpact_web.core.navigation import nav_items, page_help


def site(request):
    """Values every page template uses."""
    return {
        "climpact_web_version": climpact_web.__version__,
        "show_language_switcher": len(settings.LANGUAGES) > 1,
        "is_hosted": settings.IS_HOSTED,
        "nav_items": nav_items(request),
        "page_help": page_help(request),
    }
