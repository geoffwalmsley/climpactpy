"""``{% help_topic "id" %}``: a help topic shown in place (#81).

Renders a ``<details>`` disclosure (no JavaScript needed) with the topic's title as the
summary, its explanation, and a link to the guide section with more. Options:
``summary="..."`` replaces the title; ``variant="block"`` gives the bordered disclosure of
the design system instead of the compact link-style one used beside form fields.

An unknown id raises :class:`~climpact_web.help.topics.UnknownTopic` when ``DEBUG`` is on
(and in the tests, which also check every id used in a template); otherwise it is logged
and nothing is shown, so a typo never breaks a page in production.
"""

import logging

from django import template
from django.conf import settings

from climpact_web.help.guides import get_guide
from climpact_web.help.topics import UnknownTopic, get_topic

register = template.Library()
logger = logging.getLogger(__name__)


@register.inclusion_tag("help/_topic.html")
def help_topic(topic_id, summary=None, variant="compact"):
    try:
        topic = get_topic(topic_id)
    except UnknownTopic:
        if settings.DEBUG or getattr(settings, "HELP_STRICT", False):
            raise
        logger.error("unknown help topic %r", topic_id)
        return {"topic": None}
    guide = get_guide(topic.guide) if topic.guide else None
    return {
        "topic": topic,
        "summary": summary or topic.title,
        "variant": variant,
        "guide_title": guide.title if guide else None,
    }
