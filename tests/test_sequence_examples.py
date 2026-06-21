"""End-to-end, hermetic integration tests for the sequence-conformance path.

Where :mod:`tests.test_cli_sequence` pins focused CLI behaviors, this file
exercises the whole sequence pipeline through the public surface: read timeline ->
extract layout -> deterministic verdict -> rendered projection, plus the optional
replykit agent layer (driven by a :class:`replykit.ScriptedModel`, never a live
model), the deterministic ``--fix`` round-trip, and proof that the shipped
``examples/`` script + ``.otio`` fixtures run offline.

Nothing here touches an NLE, the network, or a real LLM. OTIO's ``otio_json``
adapter ships with opentimelineio, so the ``.otio`` interop needs no plugin.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("opentimelineio")

import conforma  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"
PASS_SEQ = EXAMPLES_DIR / "seq_netflix_pass.otio"
FAIL_SEQ = EXAMPLES_DIR / "seq_netflix_fail.otio"


def _load(seq_path: Path) -> conforma.SequenceLayout:
    timeline = conforma.read_timeline(str(seq_path))
    return conforma.extract_layout(timeline, source=seq_path.name)


# --- the deterministic core end to end -------------------------------------


def test_pass_fixture_is_conformant() -> None:
    spec = conforma.load_seq_preset("netflix-imf")
    report = conforma.SequenceConformanceAgent().check(spec, _load(PASS_SEQ))
    assert report.conformant is True
    assert report.counts()["fail"] == 0
    assert report.counts()["unknown"] == 0


def test_fail_fixture_is_non_conformant_with_expected_failures() -> None:
    spec = conforma.load_seq_preset("netflix-imf")
    report = conforma.SequenceConformanceAgent().check(spec, _load(FAIL_SEQ))
    assert report.conformant is False
    by_key = {r.key: r for r in report.results}
    assert by_key["slate_duration"].status == conforma.SeqCheckStatus.FAIL
    assert by_key["reference_audio_muted"].status == conforma.SeqCheckStatus.FAIL


def test_layout_extraction_facts() -> None:
    """The extracted layout reports the structural facts the rules depend on."""
    layout = _load(PASS_SEQ)
    assert layout.video_track_count == 1
    assert layout.audio_track_count == 4
    assert layout.slate_clip is not None
    assert layout.slate_clip.name == "SLATE"
    # Deterministic role inference found the reference track by keyword.
    roles = {t.name: t.role for t in layout.tracks if t.kind == "audio"}
    assert any(role == "reference" for role in roles.values())


def test_report_dict_round_trips_through_json() -> None:
    spec = conforma.load_seq_preset("netflix-imf")
    report = conforma.SequenceConformanceAgent().check(spec, _load(FAIL_SEQ))
    payload = conforma.sequence_report_to_dict(report)
    # The canonical --json shape must survive a json.dumps/loads round trip.
    assert json.loads(json.dumps(payload)) == payload
    assert payload["conformant"] is False


def test_markdown_render_is_deterministic() -> None:
    spec = conforma.load_seq_preset("netflix-imf")
    report = conforma.SequenceConformanceAgent().check(spec, _load(FAIL_SEQ))
    a = conforma.render_sequence_report_markdown(report)
    b = conforma.render_sequence_report_markdown(report)
    assert a == b  # diffable, stable CI artifact
    assert "NON-CONFORMANT" in a


# --- adapter capability ----------------------------------------------------


def test_otio_json_adapter_always_available() -> None:
    """otio_json ships with opentimelineio, so .otio always works offline."""
    adapters = conforma.available_adapters()
    assert adapters["otio_json"] is True
    assert conforma.adapter_available(".otio") is True
    assert conforma.adapter_available("otio") is True


# --- deterministic --fix round-trip ----------------------------------------


def test_fix_mutes_reference_and_does_not_mutate_source(tmp_path) -> None:
    spec = conforma.load_seq_preset("netflix-imf")
    timeline = conforma.read_timeline(str(FAIL_SEQ))
    layout = conforma.extract_layout(timeline, source=FAIL_SEQ.name)
    report = conforma.SequenceConformanceAgent().check(spec, layout)

    # The source reference track is enabled (the FAIL condition).
    src_ref = [t for t in layout.tracks if t.role == "reference"]
    assert src_ref and all(t.enabled for t in src_ref)

    out = tmp_path / "fixed.otio"
    conforma.fix_sequence(timeline, layout, report, str(out))

    # Re-read the corrected timeline: the reference track is now muted.
    fixed_layout = conforma.extract_layout(conforma.read_timeline(str(out)), source=str(out))
    fixed_ref = [t for t in fixed_layout.tracks if t.role == "reference"]
    assert fixed_ref and all(t.enabled is False for t in fixed_ref)

    # The source layout's reference track is unchanged (deep-copy correction).
    src_again = [t for t in layout.tracks if t.role == "reference"]
    assert all(t.enabled for t in src_again)


def test_apply_fixes_flags_slate_without_fabricating_frames(tmp_path) -> None:
    spec = conforma.load_seq_preset("netflix-imf")
    timeline = conforma.read_timeline(str(FAIL_SEQ))
    layout = conforma.extract_layout(timeline, source=FAIL_SEQ.name)
    report = conforma.SequenceConformanceAgent().check(spec, layout)
    corrected = conforma.apply_fixes(timeline, layout, report)

    import opentimelineio as otio

    flagged = False
    for track in corrected.tracks:
        if str(getattr(track, "kind", "")).lower() != "video":
            continue
        for child in track:
            if isinstance(child, otio.schema.Clip) and "conforma_flag" in child.metadata:
                flagged = True
    assert flagged, "the slate clip should carry a conforma_flag note"


# --- optional agent layer (hermetic, ScriptedModel) ------------------------


def test_agent_fills_ambiguous_role_then_deterministic_rule_consumes_it() -> None:
    """A model classifies an ambiguous audio track; the verdict stays deterministic."""
    import opentimelineio as otio
    from replykit import ScriptedModel

    rate = 24

    def rt(sec: float) -> otio.opentime.RationalTime:
        return otio.opentime.RationalTime(round(sec * rate), rate)

    def clip(name: str, dur: float) -> otio.schema.Clip:
        return otio.schema.Clip(name=name, source_range=otio.opentime.TimeRange(rt(0), rt(dur)))

    tl = otio.schema.Timeline(name="Ambiguous")
    v = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    v.append(clip("SLATE", 5.0))
    tl.tracks.append(v)
    # A track with no role keyword anywhere -> deterministic role 'unknown'.
    amb = otio.schema.Track(name="Stem A", kind=otio.schema.TrackKind.Audio)
    amb.enabled = True
    amb.append(clip("Aurora_mix_v4", 30.0))
    tl.tracks.append(amb)

    layout = conforma.extract_layout(tl, source="amb.otio")
    assert [t.role for t in layout.tracks if t.name == "Stem A"] == ["unknown"]

    refined = conforma.infer_ambiguous_roles(layout, ScriptedModel(["reference"]))
    assert [t.role for t in refined.tracks if t.name == "Stem A"] == ["reference"]


def test_deterministic_role_always_wins_over_model() -> None:
    """A keyword-resolved track is never sent to the model (deterministic wins)."""
    layout = _load(PASS_SEQ)
    # All audio tracks here are keyword-resolvable -> no ambiguity to send out.
    from replykit import ScriptedModel

    model = ScriptedModel(["this reply must never be consumed"])
    refined = conforma.infer_ambiguous_roles(layout, model)
    assert refined is layout  # nothing ambiguous -> the same object, no model call


def test_agent_narrative_is_hermetic_and_grounded() -> None:
    """The replykit agent narrates a sequence report without a live model."""
    from replykit import ScriptedModel

    spec = conforma.load_seq_preset("netflix-imf")
    layout = _load(FAIL_SEQ)
    base = conforma.SequenceConformanceAgent().check(spec, layout)
    assert base.conformant is False

    summary = conforma.explain_sequence_report(
        base, layout, ScriptedModel(["The slate is too short and the ref stem is live."])
    )
    assert isinstance(summary, str) and summary


def test_agent_check_with_model_adds_summary_but_keeps_verdict() -> None:
    from replykit import ScriptedModel

    spec = conforma.load_seq_preset("netflix-imf")
    layout = _load(FAIL_SEQ)
    deterministic = conforma.SequenceConformanceAgent().check(spec, layout)
    # One scripted reply for the narrative (the fixtures have no ambiguous roles).
    with_model = conforma.SequenceConformanceAgent(ScriptedModel(["Audit narrative here."])).check(
        spec, layout
    )
    assert with_model.conformant == deterministic.conformant
    assert with_model.llm_summary
    # Verdicts (per-rule statuses) are identical with or without the model.
    det_status = {r.key: r.status for r in deterministic.results}
    mod_status = {r.key: r.status for r in with_model.results}
    assert det_status == mod_status


# --- shipped example script + fixtures run offline -------------------------


def test_example_script_runs() -> None:
    """examples/check_sequence.py runs hermetically end to end."""
    path = EXAMPLES_DIR / "check_sequence.py"
    assert path.exists(), "missing example: check_sequence.py"
    completed = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "CONFORMANT" in completed.stdout


def test_example_script_is_importable() -> None:
    spec = importlib.util.spec_from_file_location(
        "_conforma_example_check_sequence", EXAMPLES_DIR / "check_sequence.py"
    )
    assert spec is not None and spec.loader is not None


def test_example_otio_fixtures_are_valid_timelines() -> None:
    """Both committed .otio fixtures read and extract through the public API."""
    for seq_path in (PASS_SEQ, FAIL_SEQ):
        layout = _load(seq_path)
        assert layout.timeline_name
        assert layout.video_track_count >= 1


# --- preset surface --------------------------------------------------------


def test_netflix_imf_preset_listed_and_loadable() -> None:
    assert "netflix-imf" in conforma.list_seq_presets()
    spec = conforma.load_seq_preset("netflix-imf")
    assert spec.slate_required is True
    assert spec.slate_duration_seconds == 5
    assert spec.reference_audio_must_be_muted is True
