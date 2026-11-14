"""WSGI entry point, for the local server (waitress) and hosted deployments (#12)."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "climpact_web.settings")

application = get_wsgi_application()
