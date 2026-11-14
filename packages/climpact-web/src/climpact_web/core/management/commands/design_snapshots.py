"""Save the landing page and pattern library as static HTML for design review (#71).

    climpact-web manage design_snapshots <folder>

Writes ``index.html`` (landing page), ``patterns.html`` (pattern library), ``404.html`` and
a dark-theme copy of each (``*-dark.html``), with the static files copied alongside, so
the pages open straight from disk (``file://``) in any browser without a server. The icon
sprite is inlined, since browsers will not load an external sprite from ``file://``.
"""

import re
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client, override_settings

STATIC_APP = Path(__file__).resolve().parents[2] / "static" / "climpact_web"
SPRITE_URL = "static/climpact_web/icons/icons.svg"

PAGES = {"index": "/", "patterns": "/patterns/", "404": "/this-page-does-not-exist/"}


def to_static_files(html: str) -> str:
    """Point static URLs at the copied folder and inline the icon sprite."""
    static_url = "/" + settings.STATIC_URL.lstrip("/")
    html = html.replace(f'"{static_url}', '"static/')
    sprite = (STATIC_APP / "icons" / "icons.svg").read_text()
    sprite = re.sub(r"<!--.*?-->", "", sprite, flags=re.S)
    sprite = sprite.replace("<svg ", '<svg hidden aria-hidden="true" ', 1)
    html = html.replace(f'href="{SPRITE_URL}#', 'href="#')
    return re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + sprite, html, count=1)


def dark(html: str) -> str:
    html = html.replace("<html ", '<html data-theme="dark" ', 1)
    return html.replace(
        'media="(prefers-color-scheme: dark)" id="theme-dark"', 'media="all" id="theme-dark"'
    )


class Command(BaseCommand):
    help = "Save the landing page and pattern library as static HTML for design review."

    def add_arguments(self, parser):
        parser.add_argument("folder", type=Path)

    def handle(self, *args, folder: Path, **options):
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "static" / "climpact_web"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(STATIC_APP, target)
        with override_settings(
            PATTERN_LIBRARY=True,
            ALLOWED_HOSTS=["testserver"],
            SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
            MESSAGE_STORAGE="django.contrib.messages.storage.cookie.CookieStorage",
        ):
            client = Client()
            for name, url in PAGES.items():
                response = client.get(url)
                expected = 404 if name == "404" else 200
                if response.status_code != expected:
                    raise RuntimeError(f"{url} answered {response.status_code}")
                html = to_static_files(response.content.decode())
                (folder / f"{name}.html").write_text(html)
                (folder / f"{name}-dark.html").write_text(dark(html))
        self.stdout.write(f"wrote {', '.join(PAGES)} (light and dark) to {folder}")
