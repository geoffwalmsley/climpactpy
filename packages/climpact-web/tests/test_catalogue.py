"""The English message catalogue is current: ``makemessages`` would add or drop no message.

The test copies the package to a temporary folder, runs ``makemessages -l en
--no-obsolete`` there and compares the set of messages (context, message id, plural id) in
the regenerated ``django.po`` with the committed one. It compares messages rather than the
whole file, so a change that only moves strings to other lines (the ``#:`` location
comments), the ``POT-Creation-Date`` header or another gettext version's line wrapping
does not fail it.

``makemessages`` needs GNU gettext (``xgettext``, ``msgmerge``, ``msguniq``,
``msgattrib``). Without it the test skips, unless ``CLIMPACT_REQUIRE_GETTEXT`` is set
(CI), when it fails.
"""

import ast
import os
import re
import shutil
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import override_settings

import climpact_web

PACKAGE = Path(climpact_web.__file__).parent
CATALOGUE = Path("locale", "en", "LC_MESSAGES", "django.po")
GETTEXT_TOOLS = ("xgettext", "msgmerge", "msguniq", "msgattrib")
REFRESH = (
    "cd packages/climpact-web/src/climpact_web && "
    "uv run climpact-web manage makemessages -l en --no-obsolete"
)

Message = tuple[str | None, str, str | None]

KEYWORD = re.compile(r"^(msgctxt|msgid|msgid_plural|msgstr(?:\[\d+\])?)\s+(\".*\")\s*$")
CONTINUATION = re.compile(r'^(".*")\s*$')


def messages(po: str) -> set[Message]:
    """The (context, message id, plural id) of every entry in a ``.po`` file, without the
    header entry and obsolete (``#~``) entries. Entries are separated by blank lines, as
    gettext writes them."""
    found: set[Message] = set()
    entry: dict[str, str] = {}
    field = None

    def finish():
        if "msgid" in entry and entry["msgid"]:
            found.add((entry.get("msgctxt"), entry["msgid"], entry.get("msgid_plural")))
        entry.clear()

    for line in po.splitlines():
        if match := KEYWORD.match(line):
            field, text = match.groups()
            entry[field] = ast.literal_eval(text)
        elif (match := CONTINUATION.match(line)) and field:
            entry[field] += ast.literal_eval(match.group(1))
        elif not line.strip():
            finish()
            field = None
    finish()
    return found


def test_messages_parses_entries():
    po = "\n".join(
        [
            'msgid ""',
            'msgstr ""',
            '"Language: en\\n"',
            "",
            "#: a.py:1",
            'msgid "One"',
            'msgstr ""',
            "",
            'msgctxt "unit"',
            'msgid ""',
            '"Two "',
            '"lines"',
            'msgid_plural "Twos"',
            'msgstr[0] ""',
            'msgstr[1] ""',
            "",
            '#~ msgid "Gone"',
            '#~ msgstr ""',
            "",
        ]
    )
    assert messages(po) == {(None, "One", None), ("unit", "Two lines", "Twos")}


def gettext_available() -> bool:
    missing = [tool for tool in GETTEXT_TOOLS if shutil.which(tool) is None]
    if missing and os.environ.get("CLIMPACT_REQUIRE_GETTEXT"):
        pytest.fail(f"CLIMPACT_REQUIRE_GETTEXT is set but GNU gettext is missing: {missing}")
    return not missing


def test_catalogue_is_current(tmp_path, monkeypatch):
    if not gettext_available():
        pytest.skip("GNU gettext (xgettext) is not installed")
    copy = tmp_path / "climpact_web"
    shutil.copytree(PACKAGE, copy, ignore=shutil.ignore_patterns("__pycache__"))
    # makemessages scans the current folder and writes to LOCALE_PATHS, then ./locale;
    # point both at the copy so the committed catalogue is never touched.
    monkeypatch.chdir(copy)
    with override_settings(LOCALE_PATHS=[copy / "locale"]):
        call_command("makemessages", locale=["en"], no_obsolete=True, verbosity=0)

    committed = messages((PACKAGE / CATALOGUE).read_text(encoding="utf-8"))
    regenerated = messages((copy / CATALOGUE).read_text(encoding="utf-8"))
    added = sorted(regenerated - committed, key=repr)
    dropped = sorted(committed - regenerated, key=repr)
    assert not (added or dropped), (
        f"The English message catalogue is stale: {len(added)} message(s) to add, "
        f"{len(dropped)} to drop. Refresh it with\n  {REFRESH}\n"
        f"To add: {added[:10]}\nTo drop: {dropped[:10]}"
    )
