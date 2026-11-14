"""Shared pytest hooks for the climpact-web tests."""

import sys


def pytest_terminal_summary(terminalreporter):
    """The page sizes measured by test_page_budget.py (#82), largest first."""
    module = sys.modules.get("test_page_budget")
    measured = getattr(module, "MEASURED", None)
    if not measured:
        return
    kb = 1024
    write = terminalreporter.write_line
    terminalreporter.write_sep("-", "page sizes (#82): HTML and everything it links")
    write(f"{'page':34} {'HTML':>8} {'HTML gz':>8} {'total':>8} {'gzip':>8} {'brotli':>8}  KB")
    for name, s in sorted(measured.items(), key=lambda item: -item[1]["gz"]):
        write(
            f"{name:34} {s['html_raw'] / kb:8.1f} {s['html_gz'] / kb:8.1f} {s['raw'] / kb:8.1f}"
            f" {s['gz'] / kb:8.1f} {s['br'] / kb:8.1f}"
        )
    write(
        f"budgets: landing {module.FIRST_PAGE_BUDGET // kb} KB gzip, other pages "
        f"{module.PAGE_BUDGET // kb} KB gzip, HTML {module.HTML_RAW_BUDGET // kb} KB raw"
    )
