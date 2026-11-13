"""The core package stands alone: nothing in packages/climpact imports the web package."""

import ast
from pathlib import Path

CORE = Path(__file__).parents[1]


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_core_does_not_import_the_web_package():
    files = sorted(CORE.rglob("*.py"))
    assert any(p.name == "cli.py" for p in files)
    offenders = [
        str(p.relative_to(CORE))
        for p in files
        if any(n.split(".")[0] == "climpact_web" for n in _imports(p))
    ]
    assert not offenders, f"imports climpact_web: {offenders}"
