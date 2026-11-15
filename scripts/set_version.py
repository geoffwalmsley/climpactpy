"""Set the version of both packages for a release (#131, RELEASING.md).

    uv run python scripts/set_version.py 0.1.0rc1
    uv lock

climpact and climpact-web share one version number. This writes it to the three places
that hold it: both `__version__` values (hatch reads the package versions from them) and
climpact-web's pin `climpact[plots]==X.Y.Z`. Then run `uv lock` so uv.lock records the
new versions, and add the CHANGELOG.md entry.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    (
        ROOT / "packages/climpact/src/climpact/__init__.py",
        re.compile(r'^__version__ = "[^"]*"$', re.MULTILINE),
        '__version__ = "{}"',
    ),
    (
        ROOT / "packages/climpact-web/src/climpact_web/__init__.py",
        re.compile(r'^__version__ = "[^"]*"$', re.MULTILINE),
        '__version__ = "{}"',
    ),
    (
        ROOT / "packages/climpact-web/pyproject.toml",
        re.compile(r'"climpact\[plots\]==[^"]*"'),
        '"climpact[plots]=={}"',
    ),
]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        version = Version(argv[0])
    except InvalidVersion:
        print(f"{argv[0]!r} is not a valid version (PEP 440)", file=sys.stderr)
        return 2
    if str(version) != argv[0]:
        print(f"write the version in its normal form: {version}", file=sys.stderr)
        return 2
    for path, pattern, template in FILES:
        text = path.read_text()
        new, count = pattern.subn(template.format(version), text)
        if count != 1:
            print(f"{path.relative_to(ROOT)}: expected one match, found {count}", file=sys.stderr)
            return 1
        path.write_text(new)
        print(f"{path.relative_to(ROOT)}: {version}")
    print("Now run `uv lock` and add the CHANGELOG.md entry.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
