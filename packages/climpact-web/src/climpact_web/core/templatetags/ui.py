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
