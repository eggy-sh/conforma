"""Unit tests for the optional replykit agent layer (:mod:`conforma.sequence.agent`).

All model paths use a hermetic :class:`replykit.ScriptedModel` — no network, no
live LLM. The default (``model=None``) path is fully deterministic and is what the
CLI offline mode + the bulk of the suite exercise.
"""

from __future__ import annotations

from typing import Any

from replykit import Action, ScriptedModel

from conforma.sequence.agent import (
    SequenceConformanceAgent,
    build_sequence_registry,
    explain_sequence_report,
    infer_ambiguous_roles,
)
from conforma.sequence.models import SeqCheckStatus
from conforma.sequence.rules import check_all_sequence


def test_check_no_model_is_deterministic(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    layout = layout_fixture("seq_netflix_fail.otio")
    report = SequenceConformanceAgent(model=None).check(netflix_imf_spec, layout)
    # No narrative on the deterministic path.
    assert report.llm_summary == ""
    # Verdicts equal a fresh deterministic check.
    raw = check_all_sequence(layout, netflix_imf_spec)
    assert [(r.key, r.status) for r in report.results] == [(r.key, r.status) for r in raw]
    assert report.conformant is False


def test_check_pass_layout_conformant(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    layout = layout_fixture("seq_netflix_pass.otio")
    report = SequenceConformanceAgent().check(netflix_imf_spec, layout)
    assert report.conformant is True
    assert all(r.status == SeqCheckStatus.PASS for r in report.results)


def test_infer_ambiguous_roles_fills_only_unknown(
    layout_fixture: Any,
) -> None:
    layout = layout_fixture("seq_2pop_ambiguous.otio")
    # Exactly one ambiguous audio track ("Stem Foxtrot").
    ambiguous = [t.name for t in layout.tracks if t.kind == "audio" and t.role == "unknown"]
    assert ambiguous == ["Stem Foxtrot"]

    model = ScriptedModel(["music"])
    new_layout = infer_ambiguous_roles(layout, model)
    roles = {t.name: t.role for t in new_layout.tracks if t.kind == "audio"}
    # The model filled the unknown track...
    assert roles["Stem Foxtrot"] == "music"
    # ...but never overrode the deterministic keyword match.
    assert roles["REF 2pop temp"] == "reference"
    assert roles["DX"] == "dialogue"
    assert roles["M&E"] == "me"


def test_infer_ambiguous_roles_does_not_mutate_input(layout_fixture: Any) -> None:
    layout = layout_fixture("seq_2pop_ambiguous.otio")
    model = ScriptedModel(["reference"])
    infer_ambiguous_roles(layout, model)
    # Original layout unchanged (Stem Foxtrot still unknown).
    foxtrot = next(t for t in layout.tracks if t.name == "Stem Foxtrot")
    assert foxtrot.role == "unknown"


def test_infer_ambiguous_roles_noop_when_none_unknown(
    layout_fixture: Any,
) -> None:
    layout = layout_fixture("seq_netflix_pass.otio")  # all roles resolved
    model = ScriptedModel([])  # would raise if called
    result = infer_ambiguous_roles(layout, model)
    assert result is layout


def test_infer_ambiguous_unparseable_answer_stays_unknown(layout_fixture: Any) -> None:
    layout = layout_fixture("seq_2pop_ambiguous.otio")
    # An answer carrying none of the role words -> the gap is left honest.
    model = ScriptedModel(["Unsure."])
    new_layout = infer_ambiguous_roles(layout, model)
    foxtrot = next(t for t in new_layout.tracks if t.name == "Stem Foxtrot")
    # No role word recognized -> not fabricated; the track stays 'unknown'.
    assert foxtrot.role == "unknown"


def test_explain_sequence_report_returns_scripted_answer(
    layout_fixture: Any, netflix_imf_spec: Any
) -> None:
    layout = layout_fixture("seq_netflix_fail.otio")
    report = SequenceConformanceAgent().check(netflix_imf_spec, layout)
    model = ScriptedModel(["The timeline fails several IMF delivery requirements."])
    summary = explain_sequence_report(report, layout, model)
    assert summary == "The timeline fails several IMF delivery requirements."
    # Verdict unchanged by explanation.
    assert report.conformant is False


def test_check_with_model_sets_summary_not_verdict(
    layout_fixture: Any, netflix_imf_spec: Any
) -> None:
    layout = layout_fixture("seq_netflix_fail.otio")
    # No ambiguous tracks in the fail fixture, so check() makes exactly one model
    # call: the narrative.
    ambiguous = [t for t in layout.tracks if t.kind == "audio" and t.role == "unknown"]
    assert ambiguous == []

    model = ScriptedModel(["Non-conformant: slate too short, ref not muted."])
    report = SequenceConformanceAgent(model=model).check(netflix_imf_spec, layout)
    assert report.llm_summary == "Non-conformant: slate too short, ref not muted."
    # Deterministic verdict preserved.
    determ = SequenceConformanceAgent().check(netflix_imf_spec, layout)
    assert [(r.key, r.status) for r in report.results] == [
        (r.key, r.status) for r in determ.results
    ]


def test_check_with_model_role_hint_feeds_rules(
    layout_fixture: Any,
) -> None:
    from conforma.sequence.delivery_spec import parse_delivery_spec

    # A spec that requires reference audio muted but declares no track counts, so
    # only the reference rule is in play. The fail fixture has no unknown audio
    # tracks, so we use the 2pop fixture whose 'Stem Foxtrot' is unknown.
    spec = parse_delivery_spec(
        {
            "name": "x",
            "version": "1",
            "sequence": {"reference_audio_must_be_muted": True},
        }
    )
    layout = layout_fixture("seq_2pop_ambiguous.otio")
    # Model classifies the ambiguous (unmuted) track as 'reference' -> now the
    # muted rule has another reference track to flag. 1 role call + 1 narrative.
    model = ScriptedModel(["reference", "Two reference stems remain unmuted."])
    report = SequenceConformanceAgent(model=model).check(spec, layout)
    ref_result = next(r for r in report.results if r.key == "reference_audio_muted")
    assert ref_result.status == SeqCheckStatus.FAIL
    assert report.llm_summary == "Two reference stems remain unmuted."


def test_build_sequence_registry_tools_are_grounded(
    layout_fixture: Any, netflix_imf_spec: Any
) -> None:
    layout = layout_fixture("seq_netflix_fail.otio")
    report = SequenceConformanceAgent().check(netflix_imf_spec, layout)
    registry = build_sequence_registry(layout, report)

    assert "get_result" in registry
    assert "describe_track" in registry

    # get_result(key) returns the deterministic verdict, never invented.
    got = registry.dispatch(Action(tool="get_result", args={"key": "slate_duration"}, raw=""))
    assert got.ok
    assert "slate_duration" in got.value
    assert "fail" in got.value

    # describe_track(name) returns factual track data.
    desc = registry.dispatch(Action(tool="describe_track", args={"name": "REF 2pop"}, raw=""))
    assert desc.ok
    assert "REF 2pop" in desc.value
    assert "role=reference" in desc.value
    assert "enabled=True" in desc.value


def test_build_sequence_registry_unknown_lookups_safe(
    layout_fixture: Any, netflix_imf_spec: Any
) -> None:
    layout = layout_fixture("seq_netflix_pass.otio")
    report = SequenceConformanceAgent().check(netflix_imf_spec, layout)
    registry = build_sequence_registry(layout, report)

    got = registry.dispatch(Action(tool="get_result", args={"key": "nope"}, raw=""))
    assert "no such rule" in got.value
    desc = registry.dispatch(Action(tool="describe_track", args={"name": "nope"}, raw=""))
    assert "no such track" in desc.value
