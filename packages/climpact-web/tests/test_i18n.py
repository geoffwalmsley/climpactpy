"""Translation scaffolding: every template string is marked for translation."""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

import climpact_web

PACKAGE = Path(climpact_web.__file__).parent
TEMPLATES = sorted(PACKAGE.rglob("templates/**/*.html"))

# Everything that is not visible text: translation blocks, tags, variables, comments,
# HTML tags and entities, and the content of <code> elements (names, not prose).
NOT_TEXT = [
    r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}",
    r"\{%\s*blocktranslate.*?\{%\s*endblocktranslate\s*%\}",
    r"\{%.*?%\}",
    r"\{\{.*?\}\}",
    r"\{#.*?#\}",
    r"<code>.*?</code>",
    r"<script.*?</script>",
    r"<style.*?</style>",
    r"<[^>]*>",
    r"&[a-z]+;",
]


def untranslated_text(source: str) -> str:
    for pattern in NOT_TEXT:
        source = re.sub(pattern, " ", source, flags=re.S)
    return source.strip()


# Attributes whose values people read (screen readers, tooltips, placeholders).
READ_ATTRIBUTES = re.compile(r'\b(aria-label|title|placeholder|alt|data-message)="([^"]*)"')


def untranslated_attributes(source: str) -> list[str]:
    """Readable attribute values written as plain text instead of a translation tag or a
    variable (``{% translate %}`` inside the attribute, or ``{{ label }}``)."""
    return [
        f"{name}={value!r}"
        for name, value in READ_ATTRIBUTES.findall(source)
        if value.strip() and "{%" not in value and "{{" not in value
    ]


def test_templates_found():
    assert any(p.name == "base.html" for p in TEMPLATES)


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_template_text_is_marked_for_translation(template):
    assert untranslated_text(template.read_text()) == ""
    assert untranslated_attributes(template.read_text()) == []


def test_untranslated_attributes_are_caught():
    assert untranslated_attributes('<button aria-label="Close">') == ["aria-label='Close'"]
    assert untranslated_attributes("<a title=\"{% translate 'Help' %}\">") == []
    assert untranslated_text("{% comment %}Parameters: label{% endcomment %}") == ""


def test_locale_middleware():
    assert "django.middleware.locale.LocaleMiddleware" in settings.MIDDLEWARE
    assert settings.USE_I18N


@pytest.mark.django_db
def test_language_switcher_hidden_with_one_language(client):
    assert len(settings.LANGUAGES) == 1
    assert 'name="language"' not in client.get("/").content.decode()


@pytest.mark.django_db
@override_settings(LANGUAGES=[("en", "English"), ("ar", "Arabic")])
def test_language_switcher_and_rtl(client):
    html = client.get("/").content.decode()
    assert 'name="language"' in html
    html = client.get("/", HTTP_ACCEPT_LANGUAGE="ar").content.decode()
    assert '<html lang="ar" dir="rtl">' in html
