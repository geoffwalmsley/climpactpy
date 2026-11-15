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
