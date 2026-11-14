"""Static file storage for both modes (#82): hashed names, compressed copies, smaller CSS.

``collectstatic`` with :class:`StaticFilesStorage` writes each file under a name that
carries a hash of its contents (``main.4c1d2e9a.css``), so WhiteNoise can tell browsers
to cache it for a year, plus gzip and Brotli copies that WhiteNoise sends to browsers
that accept them. Stylesheets lose their comments and extra whitespace on the way (the
sources stay commented). Hosted mode uses it as is; local mode uses
:class:`LocalStaticFilesStorage`, which falls back to the plain name for a file that
has not been collected, served from the package. See TECHNICAL.md, "Size budget".
"""

import re

from django.core.files.base import ContentFile
from whitenoise.storage import CompressedManifestStaticFilesStorage

# Quoted strings (kept as they are) and comments (dropped), found in one pass so that a
# quote inside a comment or a comment marker inside a string is not misread.
_CSS_TOKENS = re.compile(r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|/\*.*?\*/""", re.S)
# Spaces next to these characters never matter in CSS.
_CSS_PUNCTUATION = re.compile(r" ?([{};,]) ?")


def _squeeze(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return _CSS_PUNCTUATION.sub(r"\1", text).replace(";}", "}")


def minify_css(css: str) -> str:
    """``css`` without comments and unneeded whitespace. Quoted strings are untouched;
    runs of whitespace become one space, removed only next to ``{ } ; ,`` (and a last
    ``;`` before ``}`` goes), so selectors such as ``.a :focus`` keep their meaning."""
    out, text, last = [], [], 0
    for match in _CSS_TOKENS.finditer(css):
        text.append(css[last : match.start()])
        if match.group(1):  # a string: flush the text before it, keep the string
            out += [_squeeze("".join(text)), match.group(1)]
            text = []
        else:  # a comment counts as whitespace
            text.append(" ")
        last = match.end()
    text.append(css[last:])
    out.append(_squeeze("".join(text)))
    return "".join(out).strip()


class StaticFilesStorage(CompressedManifestStaticFilesStorage):
    """WhiteNoise's hashed, compressed storage, with stylesheets minified."""

    def _save(self, name, content):
        if name.endswith(".css"):
            content.seek(0)
            css = content.read()
            css = css.decode() if isinstance(css, bytes) else css
            content = ContentFile(minify_css(css).encode())
        return super()._save(name, content)


class LocalStaticFilesStorage(StaticFilesStorage):
    """For local mode: a file that has not been collected (``climpact-web`` collects them
    when it starts) keeps its plain name and is served from the package by WhiteNoise's
    finders, so pages never fail for want of ``collectstatic``."""

    manifest_strict = False

    def stored_name(self, name):
        try:
            return super().stored_name(name)
        except ValueError:  # not in the manifest, and not collected
            return name
