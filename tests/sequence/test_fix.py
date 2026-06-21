"""Unit tests for the deterministic corrector (:mod:`conforma.sequence.fix`)."""

from __future__ import annotations

from typing import Any

import opentimelineio as otio

from conforma.sequence.agent import SequenceConformanceAgent
from conforma.sequence.extract import extract_layout
from conforma.sequence.fix import apply_fixes, fix_sequence
from conforma.sequence.otio_io import read_timeline


def _fail_state(seq_fixture_path: Any, netflix_imf_spec: Any):
    timeline = read_timeline(seq_fixture_path("seq_netflix_fail.otio"))
    layout = extract_layout(timeline, source="seq_netflix_fail.otio")
    report = SequenceConformanceAgent().check(netflix_imf_spec, layout)
    return timeline, layout, report


def test_apply_fixes_mutes_reference_track(seq_fixture_path: Any, netflix_imf_spec: Any) -> None:
    timeline, layout, report = _fail_state(seq_fixture_path, netflix_imf_spec)
    corrected = apply_fixes(timeline, layout, report)
    ref = next(t for t in corrected.tracks if t.name == "REF 2pop")
    assert ref.enabled is False


def test_apply_fixes_flags_slate_metadata(seq_fixture_path: Any, netflix_imf_spec: Any) -> None:
    timeline, layout, report = _fail_state(seq_fixture_path, netflix_imf_spec)
    corrected = apply_fixes(timeline, layout, report)
    video = next(t for t in corrected.tracks if str(t.kind).lower() == "video")
    slate = next(c for c in video.find_clips() if c.name == "SLATE")
    assert "conforma_flag" in slate.metadata
    note = slate.metadata["conforma_flag"]
    assert "slate duration" in str(note)


def test_apply_fixes_does_not_mutate_source(seq_fixture_path: Any, netflix_imf_spec: Any) -> None:
    timeline, layout, report = _fail_state(seq_fixture_path, netflix_imf_spec)
    apply_fixes(timeline, layout, report)
    # Source timeline untouched: the ref track is still enabled and the slate has
    # no conforma flag.
    ref = next(t for t in timeline.tracks if t.name == "REF 2pop")
    assert ref.enabled is True
    video = next(t for t in timeline.tracks if str(t.kind).lower() == "video")
    slate = next(c for c in video.find_clips() if c.name == "SLATE")
    assert "conforma_flag" not in slate.metadata


def test_corrected_mute_survives_otio_json_roundtrip(
    seq_fixture_path: Any, netflix_imf_spec: Any, tmp_path: Any
) -> None:
    timeline, layout, report = _fail_state(seq_fixture_path, netflix_imf_spec)
    corrected = apply_fixes(timeline, layout, report)
    out = tmp_path / "fixed.otio"
    otio.adapters.write_to_file(corrected, str(out), "otio_json")
    reloaded = read_timeline(str(out))
    ref = next(t for t in reloaded.tracks if t.name == "REF 2pop")
    assert ref.enabled is False  # lossless round-trip preserves the mute
    # And the slate flag note survives too.
    video = next(t for t in reloaded.tracks if str(t.kind).lower() == "video")
    slate = next(c for c in video.find_clips() if c.name == "SLATE")
    assert "conforma_flag" in slate.metadata


def test_fix_sequence_writes_corrected_file(
    seq_fixture_path: Any, netflix_imf_spec: Any, tmp_path: Any
) -> None:
    timeline, layout, report = _fail_state(seq_fixture_path, netflix_imf_spec)
    out = tmp_path / "out.otio"
    returned = fix_sequence(timeline, layout, report, str(out))
    assert out.is_file()
    # The returned timeline is the corrected one (ref muted).
    ref = next(t for t in returned.tracks if t.name == "REF 2pop")
    assert ref.enabled is False
    # Re-read the written file and confirm the mute persisted.
    reloaded = read_timeline(str(out))
    ref2 = next(t for t in reloaded.tracks if t.name == "REF 2pop")
    assert ref2.enabled is False


def test_apply_fixes_noop_on_conformant_sequence(
    seq_fixture_path: Any, netflix_imf_spec: Any
) -> None:
    timeline = read_timeline(seq_fixture_path("seq_netflix_pass.otio"))
    layout = extract_layout(timeline, source="seq_netflix_pass.otio")
    report = SequenceConformanceAgent().check(netflix_imf_spec, layout)
    assert report.conformant is True
    corrected = apply_fixes(timeline, layout, report)
    # The already-muted ref track stays muted; nothing flagged on the slate.
    ref = next(t for t in corrected.tracks if t.name == "REF scratch")
    assert ref.enabled is False
    video = next(t for t in corrected.tracks if str(t.kind).lower() == "video")
    slate = next(c for c in video.find_clips() if c.name == "SLATE")
    assert "conforma_flag" not in slate.metadata
