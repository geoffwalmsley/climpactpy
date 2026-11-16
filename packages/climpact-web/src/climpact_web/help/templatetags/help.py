"""``{% section_help "id" %}``: a section's ⓘ and its help for the drawer (#177);
``{% help_topic "id" %}``: a help topic shown in place (#81).

``section_help`` renders the ⓘ beside a section heading: a link to the section's help page
(``help:section``), which ``js/drawer.js`` swaps for a button that opens the drawer
(``components/drawer.html``), and the help itself in a ``<template>`` the drawer copies.
``topics="index.txx"`` adds topics of the screen's own before the section's (an index
page adds its index), and ``title=`` names the help after something else than the
section (the index's code). An unknown id fails as ``help_topic``'s does.

Renders a ``<details>`` disclosure (no JavaScript needed) with the topic's title as the
summary, its explanation, and a link to the guide section with more. Options:
``summary="..."`` replaces the title; ``variant="block"`` gives the bordered disclosure of
the design system instead of the compact link-style one used beside form fields.

An unknown id raises :class:`~climpact_web.help.topics.UnknownTopic` when ``DEBUG`` is on
(and in the tests, which also check every id used in a template); otherwise it is logged
and nothing is shown, so a typo never breaks a page in production.
"""

import logging
from urllib.parse import urlencode

from django import template
from django.conf import settings

from climpact_web.help.guides import get_guide
from climpact_web.help.sections import (
    UnknownSection,
    get_section,
    parse_topics,
    section_context,
)
from climpact_web.help.topics import UnknownTopic, get_topic

register = template.Library()
logger = logging.getLogger(__name__)


def _strict() -> bool:
    return settings.DEBUG or getattr(settings, "HELP_STRICT", False)


@register.inclusion_tag("help/_section_help.html")
def section_help(section_id, topics=None, title=None):
    try:
        section = get_section(section_id)
        extra = parse_topics(topics)
        context = section_context(section, extra)
    except (UnknownSection, UnknownTopic):
        if _strict():
            raise
        logger.error("unknown help section %r or topics %r", section_id, topics)
        return {"section": None}
    url = section.url
    if extra:
        url += "?" + urlencode({"topics": " ".join(extra)})
    element_id = section.element_id + ("-" + "-".join(extra).replace(".", "-") if extra else "")
    return {
        **context,
        "url": url,
        "element_id": element_id.lower(),
        "title": title or section.title,
    }


@register.inclusion_tag("help/_topic.html")
def help_topic(topic_id, summary=None, variant="compact"):
    try:
        topic = get_topic(topic_id)
    except UnknownTopic:
        if _strict():
            raise
        logger.error("unknown help topic %r", topic_id)
        return {"topic": None}
    guide = get_guide(topic.guide) if topic.guide else None
    return {
        "topic": topic,
        "summary": summary or topic.question or topic.title,
        "variant": variant,
        "guide_title": guide.title if guide else None,
    }
