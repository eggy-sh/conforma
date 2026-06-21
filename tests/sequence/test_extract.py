"""Unit tests for layout extraction (:mod:`conforma.sequence.extract`)."""

from __future__ import annotations

from typing import Any

import pytest

from conforma.sequence.extract import (
    ROLE_KEYWORDS,
    extract_layout,
    find_slate,
    infer_role_deterministic,
)
from conforma.sequence.models import SequenceLayout


def _build_timeline():
    """A small in-memory timeline for the metadata/gap edge cases."""
    import opentimelineio as otio
    from opentimelineio import opentime, schema

    rate = 24.0

    def rng(start: float, dur: float) -> opentime.TimeRange:
        return opentime.TimeRange(
            opentime.RationalTime(start, rate), opentime.RationalTime(dur, rate)
        )

    tl = schema.Timeline(name="Mem")
    v = schema.Track(name="V1", kind=schema.TrackKind.Video)
    slate = schema.Clip(name="SLATE")
    slate.source_range = rng(0, 120)
    v.append(slate)
    tl.tracks.append(v)
    return otio, schema, rng, tl


def test_extract_pass_layout_counts_and_slate(layout_fixture: Any) -> None:
    layout: SequenceLayout = layout_fixture("seq_netflix_pass.otio")
    assert layout.timeline_name == "Seq Netflix Pass"
    assert layout.track_count == 5
    assert layout.video_track_count == 1
    assert layout.audio_track_count == 4
    # Slate is the first clip on the first video track.
    assert layout.slate_clip is not None
    assert layout.slate_clip.name == "SLATE"
    assert layout.slate_duration_seconds == pytest.approx(5.0)


def test_extract_clip_names_and_durations_exact(layout_fixture: Any) -> None:
    layout = layout_fixture("seq_netflix_fail.otio")
    video = next(t for t in layout.tracks if t.kind == "video")
    assert [c.name for c in video.clips] == ["SLATE", "SHOT_0010"]
    assert video.clips[0].duration_seconds == pytest.approx(2.0)
    assert video.clips[0].start_seconds == pytest.approx(0.0)
    # SHOT_0010 starts where SLATE ends (2.0s).
    assert video.clips[1].start_seconds == pytest.approx(2.0)
    assert video.clips[1].duration_seconds == pytest.approx(10.0)
    # Per-track total duration is the summed clip duration.
    assert video.total_duration_seconds == pytest.approx(12.0)


def test_extract_track_index_is_per_kind(layout_fixture: Any) -> None:
    layout = layout_fixture("seq_netflix_pass.otio")
    video = [t for t in layout.tracks if t.kind == "video"]
    audio = [t for t in layout.tracks if t.kind == "audio"]
    assert [t.index for t in video] == [1]
    assert [t.index for t in audio] == [1, 2, 3, 4]


def test_extract_enabled_flag_survives(layout_fixture: Any) -> None:
    layout = layout_fixture("seq_netflix_pass.otio")
    ref = next(t for t in layout.tracks if t.name == "REF scratch")
    assert ref.enabled is False
    dx = next(t for t in layout.tracks if t.name == "DX")
    assert dx.enabled is True


def test_extract_roles_keyword_inference(layout_fixture: Any) -> None:
    layout = layout_fixture("seq_netflix_pass.otio")
    roles = {t.name: t.role for t in layout.tracks if t.kind == "audio"}
    assert roles["DX"] == "dialogue"
    assert roles["MX music"] == "music"
    assert roles["M&E"] == "me"
    assert roles["REF scratch"] == "reference"


def test_extract_free_form_audio_role_unknown(layout_fixture: Any) -> None:
    # "Stem Foxtrot" hits no keyword -> stays 'unknown' (the agent's gap to fill).
    layout = layout_fixture("seq_2pop_ambiguous.otio")
    foxtrot = next(t for t in layout.tracks if t.name == "Stem Foxtrot")
    assert foxtrot.role == "unknown"
    # While the keyword-caught ref track still resolves deterministically.
    ref = next(t for t in layout.tracks if t.name == "REF 2pop temp")
    assert ref.role == "reference"


def test_extract_sparse_has_no_slate(layout_fixture: Any) -> None:
    layout = layout_fixture("seq_sparse.otio")
    assert layout.slate_clip is None
    assert layout.slate_duration_seconds is None
    # Free-form audio names -> all 'unknown'.
    assert all(t.role == "unknown" for t in layout.tracks if t.kind == "audio")


def test_extract_frame_rate_from_global_start(layout_fixture: Any) -> None:
    layout = layout_fixture("seq_netflix_pass.otio")
    assert layout.frame_rate == pytest.approx(24.0)


# --- infer_role_deterministic ----------------------------------------------


@pytest.mark.parametrize(
    ("track_name", "expected"),
    [
        ("REF 2pop", "reference"),
        ("scratch vox", "reference"),
        ("temp dialogue guide", "reference"),  # reference wins (checked first)
        ("M&E", "me"),
        ("Dialogue", "dialogue"),
        ("DX stem", "dialogue"),
        ("Music score", "music"),
        ("Stem Foxtrot", "unknown"),
        ("primary", "unknown"),
    ],
)
def test_infer_role_deterministic_cases(track_name: str, expected: str) -> None:
    assert infer_role_deterministic(track_name, []) == expected


def test_infer_role_uses_clip_names_too() -> None:
    # Track name says nothing, but a clip name carries the keyword.
    assert infer_role_deterministic("Audio 3", ["ref_2pop_clip"]) == "reference"


def test_infer_role_extra_reference_keywords() -> None:
    # A studio house term extends the reference keyword set.
    assert infer_role_deterministic("HouseWIP", []) == "unknown"
    assert (
        infer_role_deterministic("HouseWIP", [], extra_reference_keywords=("housewip",))
        == "reference"
    )


def test_infer_role_no_false_positive_on_substring() -> None:
    # "me" must not fire on "theme" or "timecode"; whole-word matching only.
    assert infer_role_deterministic("theme park", []) == "unknown"


def test_role_keywords_is_data() -> None:
    assert "reference" in ROLE_KEYWORDS
    assert "2pop" in ROLE_KEYWORDS["reference"]
    assert "dialogue" in ROLE_KEYWORDS["dialogue"]


# --- find_slate -------------------------------------------------------------


def test_find_slate_picks_first_video_clip_by_position(layout_fixture: Any) -> None:
    layout = layout_fixture("seq_netflix_fail.otio")
    slate = find_slate(layout.tracks)
    assert slate is not None
    assert slate.name == "SLATE"
    assert slate.start_seconds == pytest.approx(0.0)


def test_find_slate_none_when_no_video_clips(layout_fixture: Any) -> None:
    layout = layout_fixture("seq_sparse.otio")
    assert find_slate(layout.tracks) is None


def test_layout_as_dict_is_json_safe(layout_fixture: Any) -> None:
    import json

    layout = layout_fixture("seq_netflix_pass.otio")
    payload = json.dumps(layout.as_dict())
    restored = json.loads(payload)
    assert restored["video_track_count"] == 1
    assert restored["slate_clip"]["name"] == "SLATE"


# --- In-memory edge cases ---------------------------------------------------


def test_explicit_fcpxml_audio_role_is_honored() -> None:
    # An explicit FCPXML audioRole on a track wins over keyword inference, even
    # for a free-form track name a keyword set would leave 'unknown'.
    otio, schema, rng, tl = _build_timeline()
    a = schema.Track(name="Stem Q", kind=schema.TrackKind.Audio)
    clip = schema.Clip(name="q_take")
    clip.source_range = rng(0, 240)
    a.append(clip)
    a.metadata["fcpx_xml"] = {"audioRole": "dialogue.dialogue-1"}
    tl.tracks.append(a)

    layout = extract_layout(tl, source="mem")
    stem = next(t for t in layout.tracks if t.name == "Stem Q")
    assert stem.role == "dialogue"


@pytest.mark.parametrize(
    ("audio_role", "expected"),
    [
        ("scratch-ref", "reference"),
        ("dialogue.dialogue-1", "dialogue"),
        ("music.score", "music"),
        ("effects.fx-1", "me"),
        ("totally-custom", "unknown"),
    ],
)
def test_explicit_role_mapping(audio_role: str, expected: str) -> None:
    otio, schema, rng, tl = _build_timeline()
    a = schema.Track(name="Stem", kind=schema.TrackKind.Audio)
    clip = schema.Clip(name="take")
    clip.source_range = rng(0, 120)
    a.append(clip)
    a.metadata["fcpx_xml"] = {"audioRole": audio_role}
    tl.tracks.append(a)

    layout = extract_layout(tl, source="mem")
    stem = next(t for t in layout.tracks if t.name == "Stem")
    # An unrecognized explicit role falls back to keyword inference, which also
    # leaves a free-form "Stem"/"take" name 'unknown'.
    assert stem.role == expected


def test_gap_advances_clip_start_positions() -> None:
    # A gap between clips must advance later clips' start positions (the cursor),
    # without becoming a "clip" itself.
    otio, schema, rng, tl = _build_timeline()
    a = schema.Track(name="A1", kind=schema.TrackKind.Audio)
    first = schema.Clip(name="first")
    first.source_range = rng(0, 48)  # 2s
    a.append(first)
    gap = schema.Gap()
    gap.source_range = rng(0, 24)  # 1s gap
    a.append(gap)
    second = schema.Clip(name="second")
    second.source_range = rng(0, 48)  # 2s
    a.append(second)
    tl.tracks.append(a)

    layout = extract_layout(tl, source="mem")
    track = next(t for t in layout.tracks if t.name == "A1")
    # The gap is not a clip.
    assert [c.name for c in track.clips] == ["first", "second"]
    # 'second' starts after first (2s) + gap (1s) = 3s.
    assert track.clips[1].start_seconds == pytest.approx(3.0)
    # Total track duration includes the gap (2 + 1 + 2 = 5s).
    assert track.total_duration_seconds == pytest.approx(5.0)


def test_frame_rate_falls_back_to_first_clip_rate() -> None:
    # With no global_start_time, the rate is read off the first clip's range.
    otio, schema, rng, tl = _build_timeline()
    tl.global_start_time = None
    layout = extract_layout(tl, source="mem")
    assert layout.frame_rate == pytest.approx(24.0)
