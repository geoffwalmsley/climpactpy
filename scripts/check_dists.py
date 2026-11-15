"""Check the built distributions of climpact and climpact-web (#131).

    uv build --all-packages -o dist
    uv run python scripts/check_dists.py dist [--version X.Y.Z]

Run from the repository root (CI's `dist` job and release.yml). Checks that `dist` holds
exactly one wheel and one sdist of each package, all at one version (`--version`, or both
packages' `__version__`); that each wheel ships every file tracked in git under its
`src/` package (templates, static files, help guides, sample data, migrations, data
files), except the Tailwind sources, and nothing else; that neither wheel nor sdist ships
tests or reference data; and that climpact-web requires `climpact[plots]` at exactly its
own version. Prints each wheel's file list. Exits 1 with the reasons on any failure.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent

# distribution name -> (file-name stem, package folder, import package)
PACKAGES = {
    "climpact": ("climpact", "packages/climpact", "climpact"),
    "climpact-web": ("climpact_web", "packages/climpact-web", "climpact_web"),
}
# Tracked source files deliberately left out of the wheels (pyproject.toml `exclude`).
WHEEL_EXCLUDED = {"climpact-web": ("climpact_web/core/tailwind/",)}
# Files the packages cannot work without, named so a failure is easy to read; the full
# comparison with git below catches anything else.
REQUIRED = {
    "climpact": [
        "climpact/__init__.py",
        "climpact/cli.py",
        "climpact/data/climate.indices.csv",
    ],
    "climpact-web": [
        "climpact_web/settings.py",
        "climpact_web/core/templates/base.html",
        "climpact_web/core/static/climpact_web/css/climpact.css",
        "climpact_web/help/guides/en/gridded.md",
        "climpact_web/stations/sample_data/",
        "climpact_web/gridded/sample_data/",
        "climpact_web/jobs/migrations/0001_initial.py",
        "climpact_web/locale/en/LC_MESSAGES/django.po",
    ],
}
# Never in a wheel or an sdist.
FORBIDDEN = re.compile(r"(^|/)(tests?|reference|docs)/|\.pyc$|(^|/)__pycache__/")


def version_of(folder: str, package: str) -> str:
    text = (ROOT / folder / "src" / package / "__init__.py").read_text()
    match = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if not match:
        raise SystemExit(f"no __version__ in {folder}/src/{package}/__init__.py")
    return match.group(1)


def tracked(folder: str, package: str) -> set[str]:
    """Files tracked in git under the package's src/ folder, relative to src/."""
    out = subprocess.run(
        ["git", "ls-files", "--", f"{folder}/src/{package}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    prefix = f"{folder}/src/"
    return {line.removeprefix(prefix) for line in out.splitlines() if line}


def check(dist: Path, version: str) -> list[str]:
    errors: list[str] = []
    files = sorted(p.name for p in dist.iterdir() if p.suffix in {".whl", ".gz"})
    expected = sorted(
        name
        for stem, _, _ in PACKAGES.values()
        for name in (f"{stem}-{version}-py3-none-any.whl", f"{stem}-{version}.tar.gz")
    )
    if files != expected:
        errors.append(f"{dist} holds {files}, expected {expected}")
        return errors

    for name, (stem, folder, package) in PACKAGES.items():
        # The wheel: exactly the tracked source files, plus the metadata.
        with zipfile.ZipFile(dist / f"{stem}-{version}-py3-none-any.whl") as whl:
            names = [n for n in whl.namelist() if not n.endswith("/")]
            metadata = Parser().parsestr(whl.read(f"{stem}-{version}.dist-info/METADATA").decode())
        print(f"\n{name} {version} wheel: {len(names)} files")
        for n in names:
            print(f"  {n}")
        info = f"{stem}-{version}.dist-info/"
        shipped = {n for n in names if not n.startswith(info)}
        want = {
            f for f in tracked(folder, package) if not f.startswith(WHEEL_EXCLUDED.get(name, ()))
        }
        for missing in sorted(want - shipped):
            errors.append(f"{name} wheel is missing {missing}")
        for extra in sorted(shipped - want):
            errors.append(f"{name} wheel ships {extra}, which is not a tracked source file")
        for req in REQUIRED[name]:
            if not any(n == req or (req.endswith("/") and n.startswith(req)) for n in shipped):
                errors.append(f"{name} wheel lacks the required {req}")
        if f"{info}licenses/LICENSE" not in names:
            errors.append(f"{name} wheel lacks its LICENSE")
        for n in names:
            if FORBIDDEN.search(n):
                errors.append(f"{name} wheel ships {n} (tests, reference data or bytecode)")
        if metadata["Name"] != name or metadata["Version"] != version:
            errors.append(f"{name} wheel metadata says {metadata['Name']} {metadata['Version']}")
        if name == "climpact-web":
            pins = [r for r in metadata.get_all("Requires-Dist", []) if r.startswith("climpact")]
            if pins != [f"climpact[plots]=={version}"]:
                errors.append(
                    f"climpact-web requires {pins}, expected ['climpact[plots]=={version}']"
                )

        # The sdist: the source, README, LICENSE and metadata only.
        with tarfile.open(dist / f"{stem}-{version}.tar.gz") as sdist:
            members = [PurePosixPath(m.name) for m in sdist.getmembers() if m.isfile()]
        inner = {str(PurePosixPath(*m.parts[1:])) for m in members}
        for need in ("PKG-INFO", "pyproject.toml", "README.md", "LICENSE"):
            if need not in inner:
                errors.append(f"{name} sdist lacks {need}")
        for n in sorted(inner):
            if FORBIDDEN.search(n):
                errors.append(f"{name} sdist ships {n} (tests, reference data or bytecode)")
            elif not (n.startswith(f"src/{package}/") or "/" not in n):
                errors.append(f"{name} sdist ships {n}, outside src/{package}/")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dist", type=Path, help="folder with the built wheels and sdists")
    parser.add_argument("--version", help="expected version (default: the __version__ values)")
    args = parser.parse_args(argv)

    versions = {name: version_of(folder, pkg) for name, (_, folder, pkg) in PACKAGES.items()}
    if len(set(versions.values())) != 1:
        print(f"the packages' __version__ values differ: {versions}", file=sys.stderr)
        return 1
    version = args.version or versions["climpact"]
    if version != versions["climpact"]:
        print(f"expected version {version}, but __version__ is {versions}", file=sys.stderr)
        return 1

    errors = check(args.dist, version)
    if errors:
        print(f"\n{len(errors)} problem(s) with the distributions:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"\nclimpact and climpact-web {version}: wheels and sdists OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
