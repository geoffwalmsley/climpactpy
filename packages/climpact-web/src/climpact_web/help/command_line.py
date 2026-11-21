"""The command-line guide's generated parts (#319, the HelpCli board), built from the
``climpact`` command's own parser (``climpact.cli.build_parser``), so that the guide
cannot fall out of step with the command.

``guides/<language>/command-line.md`` holds the hand-written text: what each command is
for, what it writes and an example. These markers in it are replaced before rendering:

- ``[[cli-version]]``: the climpact version the options were read from;
- ``[[cli-commands]]``: the table of the commands, each linked to its section;
- ``[[cli-command:<name>]]``: a command's synopsis and its options, a table per argparse
  group (Station, Index settings ...), each under a ``###`` heading.

A test fails when the parser has a command the guide has no marker for.

The tables are HTML, not Markdown, so that option text such as ``wsdi<n>`` or
``[KIND:]NAME`` is shown as written.
"""

from __future__ import annotations

import argparse
import html
import re
from functools import cache

from django.utils.translation import gettext

GROUP_TITLES = {
    "positional arguments": ("arguments", "Arguments"),
    "options": ("options", "Options"),
    "station": ("station", "Station"),
    "index parameters": ("settings", "Index settings"),
    "modules": ("modules", "Modules"),
    "plots and archive": ("output", "Plots and archive"),
}

MARKER = re.compile(r"^\[\[cli-(version|commands|command:([\w-]+))\]\]$", re.M)


@cache
def parser() -> argparse.ArgumentParser:
    from climpact.cli import build_parser

    return build_parser()


def commands() -> dict[str, argparse.ArgumentParser]:
    """The subcommands, in the parser's order."""
    action = next(a for a in parser()._actions if isinstance(a, argparse._SubParsersAction))
    return dict(action.choices)


def command_help() -> dict[str, str]:
    action = next(a for a in parser()._actions if isinstance(a, argparse._SubParsersAction))
    return {choice.dest: choice.help for choice in action._choices_actions}


def options(command: str) -> list[str]:
    """Every option string (``--out``) and argument (``station_file``) of a command, but
    ``--help``."""
    out = []
    for action in commands()[command]._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        out.append(action.option_strings[-1] if action.option_strings else action.dest)
    return out


_DEFAULT_IN_HELP = re.compile(r"\s*(?:\((?:default: )?([^()]*?)\)|[;,]?\s*default: ([^;()]+?))\s*$")


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def describe(action: argparse.Action) -> tuple[str, str, str]:
    """(option, default, what it does) of an argparse action, as plain text."""
    if action.option_strings:
        option = action.option_strings[-1]
        if action.nargs == 0:
            pass
        elif action.choices:
            option += " {" + ",".join(action.choices) + "}"
        else:
            metavar = action.metavar or action.dest.upper()
            if isinstance(metavar, tuple):
                metavar = " ".join(metavar)
            option += f" {metavar}"
    else:
        option = action.dest + ("…" if action.nargs in ("+", "*") else "")
    text = (action.help or "").replace("%(default)s", str(action.default)).replace("%%", "%")
    default = ""
    match = _DEFAULT_IN_HELP.search(text)
    if match and ("default" in match.group(0)):
        default = (match.group(1) or match.group(2) or "").strip()
        text = text[: match.start()]
    if action.required:
        default = gettext("required")
    elif action.nargs == 0 and not default:
        default = gettext("off")
    elif not default and action.default not in (None, [], False) and action.option_strings:
        default = str(action.default)
    return option, default, _sentence(text)


def _groups(command: str) -> list[tuple[str, str, list[argparse.Action]]]:
    out = []
    for group in commands()[command]._action_groups:
        actions = [a for a in group._group_actions if not isinstance(a, argparse._HelpAction)]
        if not actions:
            continue
        key, title = GROUP_TITLES.get(group.title, (group.title.replace(" ", "-"), group.title))
        out.append((key, gettext(title), actions))
    return out


def synopsis(command: str) -> str:
    """``climpact run [options] --out OUT station_file``."""
    parts = [f"climpact {command}"]
    actions = [a for a in commands()[command]._actions if not isinstance(a, argparse._HelpAction)]
    if any(a.option_strings and not a.required for a in actions):
        parts.append("[options]")
    for action in actions:
        if action.option_strings and action.required:
            parts.append(describe(action)[0])
    for action in actions:
        if not action.option_strings:
            parts.append(describe(action)[0])
    return " ".join(parts)


def _code(text: str, kind: str = "option") -> str:
    return f'<code class="help-{kind}">{html.escape(text)}</code>'


def _index_links(command: str, text: str, dest: str) -> str:
    """The option's text, HTML-escaped, with the index it sets linked to its page (Days for
    WSDId → /help/indices/wsdid/)."""
    from climpact_web.help.indices import INDEX_PARAMS, by_short
    from climpact_web.help.reference import index_url

    escaped = html.escape(text)
    known = by_short()
    for short, topic in INDEX_PARAMS.items():
        if topic == f"param.{dest}" and short in known:
            info = known[short]
            for name in (info.name, info.name.removesuffix("n")):
                pattern = re.compile(rf"\b{re.escape(name)}\b")
                if pattern.search(escaped):
                    link = f'<a href="{index_url(info)}">{name}</a>'
                    return pattern.sub(link, escaped, count=1)
    return escaped


def command_html(command: str) -> str:
    """A command's synopsis and options tables, as Markdown with HTML tables."""
    lines = ["```", synopsis(command), "```", ""]
    for key, title, actions in _groups(command):
        lines += [f"### {title} {{#{command}-{key}}}", ""]
        positional = all(not a.option_strings for a in actions)
        head = (
            [gettext("Argument"), gettext("What it is")]
            if positional
            else [gettext("Option"), gettext("Default"), gettext("What it does")]
        )
        rows = []
        for action in actions:
            option, default, text = describe(action)
            cells = [_code(option)]
            if not positional:
                cells.append(_code(default, "default") if default else "")
            cells.append(_index_links(command, text, action.dest))
            rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        header = "".join(f'<th scope="col">{html.escape(h)}</th>' for h in head)
        # Wrapped here, not by guides.wrap_tables, so that each region has a name of its
        # own ("climpact run: Options"), not the repeated heading's.
        label = html.escape(f"climpact {command}: {title}")
        lines += [
            f'<div class="table-wrap" tabindex="0" role="region" aria-label="{label}">',
            '<table class="table">',
            f"<thead><tr>{header}</tr></thead>",
            "<tbody>",
            *rows,
            "</tbody>",
            "</table>",
            "</div>",
            "",
        ]
    return "\n".join(lines)


def commands_html() -> str:
    head = "".join(
        f'<th scope="col">{html.escape(h)}</th>'
        for h in (gettext("Command"), gettext("What it does"))
    )
    rows = [
        f'<tr><td><a href="#{name}">{_code("climpact " + name)}</a></td>'
        f"<td>{html.escape(_sentence(text or ''))}</td></tr>"
        for name, text in command_help().items()
    ]
    return "\n".join(
        ["<table>", f"<thead><tr>{head}</tr></thead>", "<tbody>", *rows, "</tbody>", "</table>", ""]
    )


def version() -> str:
    import climpact

    return climpact.__version__


def expand(text: str) -> str:
    """The guide's Markdown with its markers replaced."""

    def replace(match: re.Match) -> str:
        what = match.group(1)
        if what == "version":
            return version()
        if what == "commands":
            return commands_html()
        name = match.group(2)
        if name not in commands():
            raise ValueError(f"command-line guide: no command {name!r}")
        return command_html(name)

    text = re.sub(r"\[\[cli-version\]\]", version(), text)
    return MARKER.sub(replace, text)


def markers(text: str) -> set[str]:
    return set(re.findall(r"\[\[cli-command:([\w-]+)\]\]", text))
