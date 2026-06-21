"""Unit tests for the OTIO read/write boundary (:mod:`conforma.sequence.otio_io`)."""

from __future__ import annotations

from typing import Any

import pytest

from conforma.sequence import otio_io
from conforma.sequence.errors import SequenceError
from conforma.sequence.otio_io import (
    SUFFIX_ADAPTERS,
    adapter_available,
    available_adapters,
    read_timeline,
    write_timeline,
)


def test_read_otio_returns_timeline_with_expected_tracks(seq_fixture_path: Any) -> None:
    import opentimelineio as otio

    timeline = read_timeline(seq_fixture_path("seq_netflix_pass.otio"))
    assert isinstance(timeline, otio.schema.Timeline)
    assert timeline.name == "Seq Netflix Pass"
    # 1 video + 4 audio tracks.
    kinds = [str(t.kind).lower() for t in timeline.tracks]
    assert kinds.count("video") == 1
    assert kinds.count("audio") == 4


def test_read_otio_preserves_clip_names_and_durations(seq_fixture_path: Any) -> None:
    timeline = read_timeline(seq_fixture_path("seq_netflix_fail.otio"))
    video = next(t for t in timeline.tracks if str(t.kind).lower() == "video")
    clips = list(video.find_clips())
    assert [c.name for c in clips] == ["SLATE", "SHOT_0010"]
    # SLATE is 2.0s in the fail fixture.
    assert clips[0].source_range.duration.to_seconds() == pytest.approx(2.0)


def test_read_otio_preserves_enabled_flag(seq_fixture_path: Any) -> None:
    # The pass fixture mutes the reference stem (enabled=False); otio_json keeps it.
    timeline = read_timeline(seq_fixture_path("seq_netflix_pass.otio"))
    ref = next(t for t in timeline.tracks if t.name == "REF scratch")
    assert ref.enabled is False
    dx = next(t for t in timeline.tracks if t.name == "DX")
    assert dx.enabled is True


def test_read_missing_file_raises_sequence_error(seq_fixture_path: Any) -> None:
    with pytest.raises(SequenceError, match="not found"):
        read_timeline(seq_fixture_path("does_not_exist.otio"))


def test_read_unsupported_suffix_raises_sequence_error(tmp_path: Any) -> None:
    bad = tmp_path / "sequence.weird"
    bad.write_text("nonsense", encoding="utf-8")
    with pytest.raises(SequenceError, match="unsupported sequence file suffix"):
        read_timeline(str(bad))


def test_read_missing_adapter_hint(monkeypatch: Any, tmp_path: Any) -> None:
    # Simulate the fcpx_xml plugin being absent: read_timeline must raise a
    # SequenceError carrying the pip-install hint, never a bare ImportError.
    fcpxml = tmp_path / "seq.fcpxml"
    fcpxml.write_text("<fcpxml></fcpxml>", encoding="utf-8")

    def _no_fcpx(adapter: str) -> bool:
        return adapter == "otio_json"

    monkeypatch.setattr(otio_io, "_adapter_importable", _no_fcpx)
    with pytest.raises(SequenceError, match=r"conforma\[adapters\]"):
        read_timeline(str(fcpxml))


def test_write_roundtrips_track_names_and_enabled(seq_fixture_path: Any, tmp_path: Any) -> None:
    timeline = read_timeline(seq_fixture_path("seq_netflix_pass.otio"))
    out = tmp_path / "roundtrip.otio"
    write_timeline(timeline, str(out))
    assert out.is_file()
    back = read_timeline(str(out))
    assert [t.name for t in back.tracks] == [t.name for t in timeline.tracks]
    ref = next(t for t in back.tracks if t.name == "REF scratch")
    assert ref.enabled is False


def test_write_missing_adapter_hint(monkeypatch: Any, tmp_path: Any, seq_fixture_path: Any) -> None:
    timeline = read_timeline(seq_fixture_path("seq_netflix_pass.otio"))

    def _no_fcpx(adapter: str) -> bool:
        return adapter == "otio_json"

    monkeypatch.setattr(otio_io, "_adapter_importable", _no_fcpx)
    with pytest.raises(SequenceError, match=r"conforma\[adapters\]"):
        write_timeline(timeline, str(tmp_path / "out.fcpxml"))


def test_adapter_available_otio_json_always_true() -> None:
    assert adapter_available(".otio") is True
    assert adapter_available("otio") is True  # leading dot optional
    assert adapter_available(".json") is True
    assert adapter_available(".unknown_suffix") is False


def test_available_adapters_reports_otio_json() -> None:
    table = available_adapters()
    assert table["otio_json"] is True
    # The full set of adapter names conforma can dispatch to is present.
    assert set(table) == set(SUFFIX_ADAPTERS.values())


def test_suffix_adapters_mapping_is_data() -> None:
    assert SUFFIX_ADAPTERS[".otio"] == "otio_json"
    assert SUFFIX_ADAPTERS[".fcpxml"] == "fcpx_xml"
    assert SUFFIX_ADAPTERS[".aaf"] == "AAF"


def test_read_fcpxml_normalizes_to_timeline(seq_fixture_path: Any) -> None:
    # The real fcpx_xml adapter import path: an exported sequence is recovered as
    # a single Timeline. Asserted only on what survives the adapter's documented
    # lossiness (clip names + durations; track names come back as -1/0).
    pytest.importorskip("otio_fcpx_xml_adapter")
    import opentimelineio as otio

    timeline = read_timeline(seq_fixture_path("seq_netflix_fail.fcpxml"))
    assert isinstance(timeline, otio.schema.Timeline)

    clip_durations = {}
    for track in timeline.tracks:
        for clip in track.find_clips():
            if clip.source_range is not None:
                clip_durations[clip.name] = clip.source_range.duration.to_seconds()
    # Clip names + durations survive even though track names do not.
    assert clip_durations["SLATE"] == pytest.approx(2.0)
    assert clip_durations["SHOT_0010"] == pytest.approx(10.0)
    assert clip_durations["ref_2pop"] == pytest.approx(12.0)


def test_normalize_serializable_collection_picks_first_timeline() -> None:
    # FCPXML *library* files come back as a SerializableCollection; the reader
    # normalizes to the first contained Timeline (document order).
    import opentimelineio as otio

    tl_a = otio.schema.Timeline(name="First")
    tl_b = otio.schema.Timeline(name="Second")
    collection = otio.schema.SerializableCollection(name="Lib", children=[tl_a, tl_b])
    result = otio_io._normalize_to_timeline(collection, path="lib.fcpxml")
    assert isinstance(result, otio.schema.Timeline)
    assert result.name == "First"


def test_normalize_plain_list_picks_first_timeline() -> None:
    import opentimelineio as otio

    tl = otio.schema.Timeline(name="Only")
    result = otio_io._normalize_to_timeline([tl], path="x.otio")
    assert result.name == "Only"


def test_normalize_no_timeline_raises() -> None:
    import opentimelineio as otio

    empty = otio.schema.SerializableCollection(name="Empty", children=[])
    with pytest.raises(SequenceError, match="no timeline found"):
        otio_io._normalize_to_timeline(empty, path="empty.fcpxml")


def test_read_garbled_otio_raises_sequence_error(tmp_path: Any) -> None:
    bad = tmp_path / "garbled.otio"
    bad.write_text("{ this is not valid otio json", encoding="utf-8")
    with pytest.raises(SequenceError, match="could not read sequence"):
        read_timeline(str(bad))


def test_write_failure_wrapped_as_sequence_error(seq_fixture_path: Any) -> None:
    timeline = read_timeline(seq_fixture_path("seq_netflix_pass.otio"))
    # Writing to a directory that does not exist makes the adapter raise; the
    # boundary wraps it as a SequenceError.
    with pytest.raises(SequenceError, match="could not write sequence"):
        write_timeline(timeline, "/nonexistent_dir_xyz/out.otio")
