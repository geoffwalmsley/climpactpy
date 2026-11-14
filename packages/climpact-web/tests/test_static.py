"""The static files ship inside the package; the vendored htmx is the recorded file."""

import hashlib
import re
from pathlib import Path

import climpact_web

STATIC = Path(climpact_web.__file__).parent / "core" / "static" / "climpact_web"


def test_static_files_in_package():
    assert (STATIC / "css" / "main.css").is_file()
    assert (STATIC / "vendor" / "htmx" / "htmx.min.js").is_file()


def test_vendored_htmx_matches_readme():
    readme = (STATIC / "vendor" / "htmx" / "README.md").read_text()
    recorded = re.search(r"SHA-256: `([0-9a-f]{64})`", readme).group(1)
    actual = hashlib.sha256((STATIC / "vendor" / "htmx" / "htmx.min.js").read_bytes())
    assert actual.hexdigest() == recorded


def test_css_uses_logical_properties():
    """Right-to-left languages: no physical left/right in the stylesheet."""
    css = (STATIC / "css" / "main.css").read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"(margin|padding|border)-(left|right)|\b(left|right)\s*:", css)
