"""Unit tests for the deterministic sequence rules (:mod:`conforma.sequence.rules`)."""

from __future__ import annotations

from typing import Any

from conforma.sequence.models import SeqCheckStatus
from conforma.sequence.rules import (
    SEQ_RULES,
    check_all_sequence,
    check_audio_track_count,
    check_reference_audio_muted,
    check_slate_duration,
    check_video_track_count,
)


def _by_key(results: list) -> dict:
    return {r.key: r for r in results}


def test_pass_layout_all_pass_and_conformant(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    layout = layout_fixture("seq_netflix_pass.otio")
    results = check_all_sequence(layout, netflix_imf_spec)
    statuses = {r.key: r.status for r in results}
    assert all(s == SeqCheckStatus.PASS for s in statuses.values()), statuses
    # No blocking failure -> conformant.
    assert not any(r.status == SeqCheckStatus.FAIL for r in results)


def test_fail_layout_flags_slate_ref_and_track_count(
    layout_fixture: Any, netflix_imf_spec: Any
) -> None:
    layout = layout_fixture("seq_netflix_fail.otio")
    results = _by_key(check_all_sequence(layout, netflix_imf_spec))
    # 2s slate vs required 5s.
    assert results["slate_duration"].status == SeqCheckStatus.FAIL
    assert results["slate_duration"].actual == 2.0
    assert results["slate_duration"].expected == 5
    # Un-muted REF 2pop reference track.
    assert results["reference_audio_muted"].status == SeqCheckStatus.FAIL
    # 2 audio tracks vs required [4, 8].
    assert results["audio_track_count"].status == SeqCheckStatus.FAIL
    assert results["audio_track_count"].actual == 2
    # Video count is fine (1).
    assert results["video_track_count"].status == SeqCheckStatus.PASS


def test_sparse_layout_unknowns_never_raise(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    layout = layout_fixture("seq_sparse.otio")
    results = _by_key(check_all_sequence(layout, netflix_imf_spec))
    # No slate clip -> duration UNKNOWN (not a fabricated FAIL).
    assert results["slate_duration"].status == SeqCheckStatus.UNKNOWN
    # No resolvable reference role -> UNKNOWN.
    assert results["reference_audio_muted"].status == SeqCheckStatus.UNKNOWN
    # Slate is required but absent -> slate_present FAIL (the one structural fail).
    assert results["slate_present"].status == SeqCheckStatus.FAIL


def test_check_all_sequence_order_is_stable(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    layout = layout_fixture("seq_netflix_pass.otio")
    results = check_all_sequence(layout, netflix_imf_spec)
    assert [r.key for r in results] == [
        "slate_present",
        "slate_duration",
        "reference_audio_muted",
        "video_track_count",
        "audio_track_count",
    ]
    assert len(SEQ_RULES) == len(results)


def test_slate_duration_within_tolerance_passes(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    # The pass fixture's slate is exactly 5.0s; 5 ±0.5 -> PASS.
    layout = layout_fixture("seq_netflix_pass.otio")
    result = check_slate_duration(layout, netflix_imf_spec)
    assert result.status == SeqCheckStatus.PASS


def test_slate_duration_unknown_when_spec_silent(layout_fixture: Any) -> None:
    from conforma.sequence.delivery_spec import parse_delivery_spec

    spec = parse_delivery_spec({"name": "x", "version": "1", "sequence": {}})
    layout = layout_fixture("seq_netflix_pass.otio")
    assert check_slate_duration(layout, spec).status == SeqCheckStatus.UNKNOWN


def test_reference_audio_muted_pass_when_muted(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    layout = layout_fixture("seq_netflix_pass.otio")
    result = check_reference_audio_muted(layout, netflix_imf_spec)
    assert result.status == SeqCheckStatus.PASS


def test_reference_audio_muted_unknown_when_not_required(layout_fixture: Any) -> None:
    from conforma.sequence.delivery_spec import parse_delivery_spec

    spec = parse_delivery_spec({"name": "x", "version": "1", "sequence": {}})
    layout = layout_fixture("seq_netflix_fail.otio")
    assert check_reference_audio_muted(layout, spec).status == SeqCheckStatus.UNKNOWN


def test_reference_keywords_extension_resolves_house_term(
    layout_fixture: Any,
) -> None:
    # A spec house term promotes an otherwise-unknown track to 'reference', so the
    # muted rule can then fire on it.
    from conforma.sequence.delivery_spec import parse_delivery_spec

    spec = parse_delivery_spec(
        {
            "name": "x",
            "version": "1",
            "sequence": {
                "reference_audio_must_be_muted": True,
                "reference_role_keywords": ["foxtrot"],
            },
        }
    )
    layout = layout_fixture("seq_2pop_ambiguous.otio")
    result = check_reference_audio_muted(layout, spec)
    # "Stem Foxtrot" (unmuted) now resolves to reference -> FAIL.
    assert result.status == SeqCheckStatus.FAIL


def test_video_track_count_pass_and_fail(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    layout = layout_fixture("seq_netflix_pass.otio")
    assert check_video_track_count(layout, netflix_imf_spec).status == SeqCheckStatus.PASS


def test_video_track_count_unknown_when_spec_silent(layout_fixture: Any) -> None:
    from conforma.sequence.delivery_spec import parse_delivery_spec

    spec = parse_delivery_spec({"name": "x", "version": "1", "sequence": {}})
    layout = layout_fixture("seq_netflix_pass.otio")
    assert check_video_track_count(layout, spec).status == SeqCheckStatus.UNKNOWN


def test_video_track_count_fail_with_fix_hint(layout_fixture: Any) -> None:
    from conforma.sequence.delivery_spec import parse_delivery_spec

    # Expect 2 video tracks; the pass fixture has 1 -> FAIL with a fix hint.
    spec = parse_delivery_spec(
        {"name": "x", "version": "1", "sequence": {"expected_video_tracks": 2}}
    )
    layout = layout_fixture("seq_netflix_pass.otio")
    result = check_video_track_count(layout, spec)
    assert result.status == SeqCheckStatus.FAIL
    assert result.actual == 1
    assert "2" in result.fix_hint


def test_audio_track_count_accepts_list_membership(
    layout_fixture: Any, netflix_imf_spec: Any
) -> None:
    # The pass fixture has 4 audio tracks; spec accepts [4, 8].
    layout = layout_fixture("seq_netflix_pass.otio")
    assert check_audio_track_count(layout, netflix_imf_spec).status == SeqCheckStatus.PASS


def test_audio_track_count_fail_outside_list(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    layout = layout_fixture("seq_netflix_fail.otio")
    result = check_audio_track_count(layout, netflix_imf_spec)
    assert result.status == SeqCheckStatus.FAIL
    assert result.actual == 2


def test_results_are_json_safe(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    import json

    layout = layout_fixture("seq_netflix_fail.otio")
    results = check_all_sequence(layout, netflix_imf_spec)
    payload = json.dumps([r.as_dict() for r in results])
    assert json.loads(payload)[0]["key"] == "slate_present"
