"""Shared fixtures for the Frml test suite."""

import pytest


@pytest.fixture
def write_frml(tmp_path):
    """Write `source` to a temporary `.frml` file and return its path."""

    def _write(source, name="prog.frml"):
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        return str(path)

    return _write
