"""Shared pytest fixtures for the sequence suite — fully hermetic.

Every fixture here is offline: timelines come from committed ``.otio`` (and one
``.fcpxml``) files under ``tests/sequence/fixtures/`` and any "LLM" is a
:class:`replykit.ScriptedModel`. No real NLE, media, or network is ever touched.
The lossless ``.otio`` fixtures drive the verdict tests; the single ``.fcpxml``
proves the real ``fcpx_xml`` adapter import path (and is asserted only on what
survives that adapter's documented lossiness).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conforma.sequence.delivery_spec import load_seq_preset
from conforma.sequence.extract import extract_layout

#: Directory holding the committed sequence fixtures.
SEQ_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def seq_fixtures_dir() -> Path:
    """Absolute path to the committed sequence-fixtures directory."""
    return SEQ_FIXTURES_DIR


@pytest.fixture
def seq_fixture_path() -> Any:
    """Return a resolver ``(name) -> str`` giving a fixture's absolute path.

    ``name`` is a filename under ``tests/sequence/fixtures/`` (suffix included,
    e.g. ``"seq_netflix_pass.otio"``).
    """

    def _path(name: str) -> str:
        return str(SEQ_FIXTURES_DIR / name)

    return _path


@pytest.fixture
def netflix_imf_spec() -> Any:
    """The shipped ``netflix-imf`` :class:`DeliverySpec`."""
    return load_seq_preset("netflix-imf")


@pytest.fixture
def read_timeline_fixture() -> Any:
    """Return a loader ``(name) -> otio.schema.Timeline`` for an .otio fixture."""
    from conforma.sequence.otio_io import read_timeline

    def _read(name: str) -> Any:
        return read_timeline(str(SEQ_FIXTURES_DIR / name))

    return _read


@pytest.fixture
def layout_fixture(read_timeline_fixture: Any) -> Any:
    """Return a loader ``(name) -> SequenceLayout`` for an .otio fixture."""

    def _layout(name: str) -> Any:
        timeline = read_timeline_fixture(name)
        return extract_layout(timeline, source=name)

    return _layout
