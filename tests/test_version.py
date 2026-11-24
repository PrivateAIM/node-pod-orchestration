"""Tests that flame_po.__version__ matches the version declared in pyproject.toml."""

import tomllib
from pathlib import Path

from flame_po import __version__


def test_version_matches_pyproject():
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == pyproject["tool"]["poetry"]["version"]
