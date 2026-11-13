"""The web package installs alongside the core package."""

import climpact
import climpact_web


def test_imports():
    assert climpact_web.__version__
    assert climpact.__version__
