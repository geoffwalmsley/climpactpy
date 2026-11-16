"""Template helpers for the design system (#71): ``{% load ui %}``."""

from django import template
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()

ICON_SPRITE = "climpact_web/icons/icons.svg"


@register.simple_tag
def icon(name, label="", css=""):
    """An icon from the sprite. Decorative (hidden from screen readers) unless ``label``
    is given, in which case it is announced as an image with that name."""
    classes = f"icon {css}".strip()
    href = f"{static(ICON_SPRITE)}#{name}"
    if label:
        return format_html(
            '<svg class="{}" role="img" aria-label="{}"><use href="{}"></use></svg>',
            classes,
            label,
            href,
        )
    return format_html(
        '<svg class="{}" aria-hidden="true" focusable="false"><use href="{}"></use></svg>',
        classes,
        href,
    )


@register.filter
def times(count, default=3):
    """``range(count)`` for repeating markup; an unset count gives ``default``."""
    if count is None or count == "":
        return range(default)
    return range(int(count))


@register.filter
def token_name(token):
    """A design token's name without its dashes, for the class that sets it (#137):
    ``swatch-{{ "--chart-tmax"|token_name }}`` is ``swatch-chart-tmax``, a class in
    charts.css, because the Content Security Policy allows no style attributes."""
    return str(token).removeprefix("--")


@register.filter
def file_size(job, relative):
    """Size in bytes of the file ``relative`` of a job's output, for download buttons
    (#79): ``{{ job|file_size:path|filesizeformat }}``; 0 when there is none."""
    from climpact_web.jobs.views import output_size

    return output_size(job, relative) if job is not None and relative else 0


@register.filter
def count(value):
    """A count as every screen shows one (#115): localised, with the thousands grouped
    (``29220`` -> ``29,220`` in English), as the chart summaries. Anything that is not a
    whole number is returned unchanged."""
    from django.utils.formats import number_format

    if isinstance(value, bool) or not isinstance(value, int):
        try:
            if isinstance(value, bool) or float(value) != int(float(value)):
                return value
            value = int(float(value))
        except (TypeError, ValueError):
            return value
    return number_format(value, force_grouping=True)


TURNSTILE_SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js"


@register.simple_tag(takes_context=True)
def turnstile(context):
    """Cloudflare Turnstile's widget, for a form that uploads a file or starts a job
    (#125): nothing unless Turnstile is on (hosted mode, both keys set; see
    :mod:`climpact_web.core.limits`). The widget adds the ``cf-turnstile-response`` field the
    view checks; it usually passes without asking anything, and is keyboard and screen
    reader accessible. Cloudflare's script is added once per page, with the first widget.

    A form sent before its widget has a token would be refused (#163), so
    ``js/turnstile.js``, added with Cloudflare's script, holds the form back until the
    token comes and then sends it: the ``data-*-callback`` names are its functions, and
    ``data-wait``, ``data-slow``, ``data-failed`` and ``data-retry`` the texts it shows."""
    from django.conf import settings
    from django.utils.translation import get_language
    from django.utils.translation import gettext as _

    from climpact_web.core.limits import turnstile_enabled

    if not turnstile_enabled():
        return ""
    widget = format_html(
        '<div class="cf-turnstile" data-sitekey="{}" data-language="{}" data-size="flexible"'
        ' data-callback="climpactTurnstileDone" data-error-callback="climpactTurnstileError"'
        ' data-wait="{}" data-slow="{}" data-failed="{}" data-retry="{}">'
        "</div><noscript><p>{}</p></noscript>",
        settings.TURNSTILE_SITE_KEY,
        get_language() or "auto",
        _("Checking that you are a person. The form is sent as soon as the check finishes."),
        _("Still checking that you are a person. If the check asks you something, answer it."),
        _(
            "We could not check that you are a person, so the form was not sent. Try "
            "again, or reload the page."
        ),
        _("Try again"),
        _(
            "This form checks that you are a person before it is sent, which needs "
            "JavaScript. Turn JavaScript on to continue."
        ),
    )
    request = context.get("request")
    if request is not None and getattr(request, "_turnstile_script", False):
        return widget
    if request is not None:
        request._turnstile_script = True
    script = format_html(
        '<script src="{}" defer></script><script src="{}" async defer></script>',
        static("climpact_web/js/turnstile.js"),
        TURNSTILE_SCRIPT,
    )
    return widget + script
