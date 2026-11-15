"""The page shell, health check, error pages and security behaviour."""

import re

import pytest
from django.test import override_settings

import climpact
import climpact_web

pytestmark = pytest.mark.django_db


def test_home(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.content.decode()
    assert '<html lang="en" dir="ltr">' in html
    assert "/static/climpact_web/css/climpact.css" in html
    assert "/static/climpact_web/vendor/htmx/htmx.min.js" in html
    assert 'href="#main"' in html  # skip link
    assert "X-CSRFToken" in html  # htmx requests carry the CSRF token


def test_pages_load_nothing_from_the_network(client):
    """Works offline: no scripts, styles, images or fonts from other hosts."""
    html = client.get("/").content.decode()
    assert not re.search(r'(src|href)="(https?:)?//', html)


def test_security_headers(client):
    response = client.get("/")
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "same-origin"


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "version": climpact_web.__version__,
        "core_version": climpact.__version__,
    }
    assert "no-cache" in response["Cache-Control"]


def test_healthz_database_down(client, monkeypatch):
    from django.db import connection

    def broken():
        raise RuntimeError("database down")

    monkeypatch.setattr(connection, "cursor", broken)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["status"] == "error"


def test_not_found(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "Page not found" in response.content.decode()


def test_home_rejects_post(client):
    assert client.post("/").status_code in {403, 405}  # CSRF or method check


@override_settings(MAX_UPLOAD_BYTES=1024, MAX_UPLOAD_MB=0.001)
def test_upload_limit(client):
    response = client.post("/", data=b"x" * 2048, content_type="application/octet-stream")
    assert response.status_code == 413
    assert "File too large" in response.content.decode()


def test_csrf_enforced():
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    assert client.post("/i18n/setlang/", {"language": "en"}).status_code == 403


def test_static_files_served_from_the_package(client):
    """WhiteNoise serves the packaged static files without collectstatic (local mode)."""
    for path in ("climpact_web/css/climpact.css", "climpact_web/vendor/htmx/htmx.min.js"):
        response = client.get(f"/static/{path}")
        assert response.status_code == 200, path
        b"".join(response.streaming_content)
