"""Shared pytest fixtures for the conforma suite — fully hermetic.

Every fixture here is offline: probe data comes from committed JSON under
``tests/fixtures/`` and any "LLM" is a :class:`replykit.ScriptedModel`. No real
ffmpeg, ffprobe, media file, or network is ever touched. Both SWE-Core (unit
tests) and SWE-CLI (integration tests) build on these fixtures.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

# Pin a wide terminal width so Rich-rendered CLI "--help" output is never
# wrapped/truncated under CI's narrow non-TTY width (which hides option flags
# from the help tests). Set at import time, before any CLI is imported/invoked.
os.environ["COLUMNS"] = "200"

#: Directory holding committed probe JSON fixtures.
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Absolute path to the committed probe-JSON fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def load_fixture() -> Any:
    """Return a loader ``(name) -> parsed JSON`` for a fixture file.

    ``name`` is a filename under ``tests/fixtures/`` (with or without the
    ``.json`` suffix). Returns the parsed Python object.
    """

    def _load(name: str) -> Any:
        fname = name if name.endswith(".json") else f"{name}.json"
        return json.loads((FIXTURES_DIR / fname).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def fixture_path() -> Any:
    """Return a resolver ``(name) -> str`` giving a fixture's absolute path.

    Handy for tests that exercise the file-loading entry points
    (``load_probe`` / the CLI) rather than passing parsed dicts.
    """

    def _path(name: str) -> str:
        fname = name if name.endswith(".json") else f"{name}.json"
        return str(FIXTURES_DIR / fname)

    return _path


@pytest.fixture
def ffprobe_netflix_pass(load_fixture: Any) -> dict[str, Any]:
    """Parsed ffprobe JSON that conforms to the netflix-hd preset."""
    return load_fixture("ffprobe_netflix_pass")


@pytest.fixture
def ffprobe_netflix_fail(load_fixture: Any) -> dict[str, Any]:
    """Parsed ffprobe JSON that violates several netflix-hd requirements."""
    return load_fixture("ffprobe_netflix_fail")


@pytest.fixture
def mediainfo_netflix_pass(load_fixture: Any) -> dict[str, Any]:
    """Parsed MediaInfo JSON equivalent to ``ffprobe_netflix_pass``.

    Used to prove probe-source-agnostic normalization: this and the ffprobe
    pass fixture must normalize to equivalent verdicts against netflix-hd.
    """
    return load_fixture("mediainfo_netflix_pass")


@pytest.fixture
def ffprobe_ebu_pass(load_fixture: Any) -> dict[str, Any]:
    """Parsed ffprobe JSON that conforms to the ebu-broadcast preset."""
    return load_fixture("ffprobe_ebu_pass")


@pytest.fixture
def ffprobe_sparse(load_fixture: Any) -> dict[str, Any]:
    """Parsed ffprobe JSON missing bit depth / scan type / audio (UNKNOWN cases)."""
    return load_fixture("ffprobe_sparse")
