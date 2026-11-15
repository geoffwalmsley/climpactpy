"""The two packages release together with one version number (#131, RELEASING.md)."""

import tomllib
from pathlib import Path

import climpact
import climpact_web

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "packages" / "climpact-web"


def test_one_version_and_the_core_pinned_to_it():
    """climpact-web requires climpact at exactly its own version, so a web install never
    gets a mismatched core; scripts/set_version.py changes all three together."""
    assert climpact.__version__ == climpact_web.__version__
    deps = tomllib.loads((WEB / "pyproject.toml").read_text())["project"]["dependencies"]
    core = [d for d in deps if d.startswith("climpact")]
    assert core == [f"climpact[plots]=={climpact.__version__}"]


def test_license_copies_match():
    """Each package ships its own copy of the root LICENSE (hatch's license-files cannot
    reach outside the package folder)."""
    root = (ROOT / "LICENSE").read_bytes()
    assert "GNU GENERAL PUBLIC LICENSE" in root.decode()[:200]
    for package in ("climpact", "climpact-web"):
        assert (ROOT / "packages" / package / "LICENSE").read_bytes() == root, package
