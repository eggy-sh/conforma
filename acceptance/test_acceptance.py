"""Hermetic, reproducible acceptance runner for conforma.

Executes EVERY scenario from ``acceptance/scenarios.md`` (S1..S12) under one set
of identical, hermetic conditions and asserts each machine-checkable success
criterion. There are no rubric/judgment-scored checks: every oracle here is exact
because every output under test is produced by conforma's deterministic
rule/format/timecode code. The single place a model is involved (S9, ambiguous
audio-track role inference) is asserted *negatively* — the model must not change a
deterministic verdict — and is driven only by ``replykit.ScriptedModel`` (no live
LLM, no network).

Hermeticity (enforced identically for every scenario):

* CLI scenarios run the installed ``conforma`` console script as a subprocess in a
  scrubbed environment whose ``PATH`` is stripped of any ``ffmpeg``/``ffprobe`` and
  whose network/proxy variables are cleared, so the CLI exercises the committed
  ``*.json`` / ``*.otio`` fixtures and never shells out or hits the network.
* Library scenarios (S8 re-parse, S9 model seam) call only the public ``conforma``
  API plus ``opentimelineio`` directly and, where a model is needed, a
  ``replykit.ScriptedModel``.

Run::

    .venv/bin/python -m pytest acceptance/test_acceptance.py -v

Each test corresponds to exactly one scenario id; a scenario passes iff every
assertion in its criterion holds.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Locations — anchored to the repo root (this file lives in <repo>/acceptance).
# --------------------------------------------------------------------------- #

REPO = Path(__file__).resolve().parent.parent
VENV_BIN = REPO / ".venv" / "bin"
CONFORMA = VENV_BIN / "conforma"
PYTHON = VENV_BIN / "python"

# The nine deterministic media rule keys (S5 schema correctness).
KNOWN_RULE_KEYS = {
    "container",
    "resolution",
    "frame_rate",
    "scan_type",
    "video_codec",
    "bit_depth",
    "audio_codec",
    "audio_channels",
    "audio_sample_rate",
}


# --------------------------------------------------------------------------- #
# Hermetic process environment — identical for every CLI scenario.
# --------------------------------------------------------------------------- #


def _hermetic_env() -> dict[str, str]:
    """Return a scrubbed env: no ffmpeg/ffprobe on PATH, no network/proxy vars.

    PATH is rebuilt from the original entries minus any directory that contains an
    ``ffmpeg`` or ``ffprobe`` binary, then guaranteed to include the project venv's
    ``bin`` (so the ``conforma`` script and its interpreter resolve). All common
    proxy / network variables are removed so a stray dependency cannot reach out.
    """
    env = dict(os.environ)
    # Drop any directory that could expose ffmpeg/ffprobe to the auto-probe path.
    kept: list[str] = []
    for entry in env.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        if shutil.which("ffmpeg", path=entry) or shutil.which("ffprobe", path=entry):
            continue
        kept.append(entry)
    kept.insert(0, str(VENV_BIN))
    env["PATH"] = os.pathsep.join(kept)
    for var in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "all_proxy",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        env.pop(var, None)
    # Belt-and-suspenders: force any replykit live backend off.
    env["NO_PROXY"] = "*"
    return env


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``conforma <args>`` hermetically from the repo root; capture text I/O."""
    return subprocess.run(
        [str(CONFORMA), *args],
        cwd=str(REPO),
        env=_hermetic_env(),
        capture_output=True,
        text=True,
    )


def parse_single_json(stdout: str) -> dict:
    """Assert stdout is exactly one JSON object and return it.

    Enforces the automation contract: ``--json`` prints one parseable object and
    nothing else. ``json.loads`` already rejects trailing junk after the object,
    so a clean parse of the whole stdout proves "exactly one object".
    """
    obj = json.loads(stdout)
    assert isinstance(obj, dict), f"stdout is not a JSON object: {stdout!r}"
    return obj


def assert_hermetic_precondition() -> None:
    """Guardrail: under the hermetic env, ffprobe must not be resolvable."""
    env = _hermetic_env()
    assert shutil.which("ffprobe", path=env["PATH"]) is None, "hermetic env leaks ffprobe on PATH"
    assert shutil.which("ffmpeg", path=env["PATH"]) is None, "hermetic env leaks ffmpeg on PATH"


@pytest.fixture(scope="session", autouse=True)
def _verify_layout() -> None:
    """Fail fast (and identically for all scenarios) if the harness is misplaced."""
    assert CONFORMA.exists(), f"conforma console script not found at {CONFORMA}"
    assert PYTHON.exists(), f"venv python not found at {PYTHON}"
    assert_hermetic_precondition()


# --------------------------------------------------------------------------- #
# S1 — check a conformant ProRes master against netflix-hd.
# --------------------------------------------------------------------------- #


def test_S1_check_conformant_netflix_hd() -> None:
    proc = run_cli("check", "examples/probe_netflix_pass.json", "--spec", "netflix-hd", "--json")
    assert proc.returncode == 0, proc.stderr
    obj = parse_single_json(proc.stdout)

    assert obj["conformant"] is True
    assert obj["counts"] == {"pass": 9, "fail": 0, "unknown": 0}
    assert obj["spec"]["name"] == "Netflix HD ProRes (approx.)"
    assert obj["spec"]["version"] == "1.0"

    results = obj["results"]
    assert len(results) == 9
    for r in results:
        assert r["status"] == "pass", r
        assert r["fix_command"] == "", r


# --------------------------------------------------------------------------- #
# S2 — non-conformant file emits exact ffmpeg fix commands per failure.
# --------------------------------------------------------------------------- #


def test_S2_check_nonconformant_with_fixes() -> None:
    proc = run_cli(
        "check",
        "tests/fixtures/ffprobe_netflix_fail.json",
        "--spec",
        "netflix-hd",
        "--json",
    )
    assert proc.returncode == 1, proc.stderr
    obj = parse_single_json(proc.stdout)

    assert obj["conformant"] is False
    assert obj["counts"] == {"pass": 3, "fail": 6, "unknown": 0}

    by_key = {r["key"]: r for r in obj["results"]}

    res = by_key["resolution"]
    assert res["status"] == "fail"
    assert res["actual"] == [1280, 720]
    assert res["expected"] == [1920, 1080]
    assert "-vf scale=1920:1080" in res["fix_command"]

    assert by_key["frame_rate"]["status"] == "fail"
    assert "-r 23.976" in by_key["frame_rate"]["fix_command"]

    assert by_key["bit_depth"]["status"] == "fail"
    assert "-pix_fmt yuv422p10le" in by_key["bit_depth"]["fix_command"]

    for r in obj["results"]:
        if r["status"] == "fail":
            assert r["fix_command"] != "", r
        elif r["status"] == "pass":
            assert r["fix_command"] == "", r


# --------------------------------------------------------------------------- #
# S3 — probe-source agnosticism: MediaInfo JSON yields the S1 per-rule verdict.
# --------------------------------------------------------------------------- #


def test_S3_mediainfo_matches_ffprobe_verdict() -> None:
    mi = run_cli(
        "check",
        "tests/fixtures/mediainfo_netflix_pass.json",
        "--spec",
        "netflix-hd",
        "--json",
    )
    assert mi.returncode == 0, mi.stderr
    mi_obj = parse_single_json(mi.stdout)
    assert mi_obj["conformant"] is True
    assert mi_obj["counts"] == {"pass": 9, "fail": 0, "unknown": 0}

    ff = run_cli("check", "examples/probe_netflix_pass.json", "--spec", "netflix-hd", "--json")
    assert ff.returncode == 0, ff.stderr
    ff_obj = parse_single_json(ff.stdout)

    mi_status = {r["key"]: r["status"] for r in mi_obj["results"]}
    ff_status = {r["key"]: r["status"] for r in ff_obj["results"]}
    assert set(mi_status) == set(ff_status)
    assert len(mi_status) == 9
    # Identical per-rule verdict map across all 9 keys (independent of surface form).
    assert mi_status == ff_status


# --------------------------------------------------------------------------- #
# S4 — custom YAML spec by path + must/should severity gating.
# --------------------------------------------------------------------------- #

ADVISORY_YAML = """\
name: Advisory Spec
version: "1.0"
requirements:
  - key: resolution
    expected: [1920, 1080]
  - key: audio_sample_rate
    expected: 96000
    severity: should
"""


def test_S4_advisory_should_does_not_gate(tmp_path: Path) -> None:
    advisory = tmp_path / "advisory.yaml"
    advisory.write_text(ADVISORY_YAML, encoding="utf-8")

    proc = run_cli("check", "examples/probe_netflix_pass.json", "--spec", str(advisory), "--json")
    assert proc.returncode == 0, proc.stderr
    obj = parse_single_json(proc.stdout)

    assert obj["conformant"] is True
    assert obj["counts"] == {"pass": 1, "fail": 1, "unknown": 0}

    by_key = {r["key"]: r for r in obj["results"]}
    asr = by_key["audio_sample_rate"]
    assert asr["status"] == "fail"
    assert asr["severity"] == "should"

    # Same command without --json (human mode) also exits 0.
    human = run_cli("check", "examples/probe_netflix_pass.json", "--spec", str(advisory))
    assert human.returncode == 0, human.stderr

    # Control: path-based custom spec with a stricter must requirement gates (exit 1).
    control = run_cli(
        "check",
        "examples/probe_netflix_pass.json",
        "--spec",
        "examples/netflix-custom.yaml",
        "--json",
    )
    assert control.returncode == 1, control.stderr
    control_obj = parse_single_json(control.stdout)
    assert control_obj["spec"]["name"] == "ACME Studios HD Mezzanine (custom)"
    assert control_obj["conformant"] is False


# --------------------------------------------------------------------------- #
# S5 — presets + show introspection / schema correctness.
# --------------------------------------------------------------------------- #


def test_S5_presets_and_show_schema() -> None:
    presets = run_cli("presets", "--json")
    assert presets.returncode == 0, presets.stderr
    pobj = parse_single_json(presets.stdout)

    items = pobj["presets"]
    names = {i["name"] for i in items}
    assert names == {"ebu-broadcast", "netflix-hd"}
    for item in items:
        assert isinstance(item["requirements"], int)
        assert item["requirements"] == 9
        assert item["spec_name"], item
        assert item["version"], item

    show = run_cli("show", "netflix-hd", "--json")
    assert show.returncode == 0, show.stderr
    sobj = parse_single_json(show.stdout)
    assert sobj["name"] == "Netflix HD ProRes (approx.)"
    assert sobj["version"] == "1.0"

    reqs = sobj["requirements"]
    assert len(reqs) == 9
    expected_keys = {"key", "expected", "tolerance", "severity", "description"}
    for req in reqs:
        assert set(req.keys()) == expected_keys, req
        assert req["key"] in KNOWN_RULE_KEYS, req
        assert req["severity"] in {"must", "should"}, req


# --------------------------------------------------------------------------- #
# S6 — sequence PASS on a conformant Netflix-IMF timeline (OTIO).
# --------------------------------------------------------------------------- #


def test_S6_sequence_pass() -> None:
    proc = run_cli("sequence", "examples/seq_netflix_pass.otio", "--spec", "netflix-imf", "--json")
    assert proc.returncode == 0, proc.stderr
    obj = parse_single_json(proc.stdout)

    assert obj["conformant"] is True
    assert obj["counts"] == {"pass": 5, "fail": 0, "unknown": 0}

    keys = [r["key"] for r in obj["results"]]
    assert keys == [
        "slate_present",
        "slate_duration",
        "reference_audio_muted",
        "video_track_count",
        "audio_track_count",
    ]
    for r in obj["results"]:
        assert r["status"] == "pass", r

    by_key = {r["key"]: r for r in obj["results"]}
    assert by_key["slate_duration"]["actual"] == 5.0
    assert by_key["reference_audio_muted"]["actual"] == "all muted"


# --------------------------------------------------------------------------- #
# S7 — sequence FAIL: short slate + live reference stem.
# --------------------------------------------------------------------------- #


def test_S7_sequence_fail() -> None:
    proc = run_cli("sequence", "examples/seq_netflix_fail.otio", "--spec", "netflix-imf", "--json")
    assert proc.returncode == 1, proc.stderr
    obj = parse_single_json(proc.stdout)

    assert obj["conformant"] is False
    assert obj["counts"] == {"pass": 3, "fail": 2, "unknown": 0}

    by_key = {r["key"]: r for r in obj["results"]}

    dur = by_key["slate_duration"]
    assert dur["status"] == "fail"
    assert dur["actual"] == 2.0
    assert dur["expected"] == 5.0
    assert dur["fix_hint"] and "5s" in dur["fix_hint"]

    ref = by_key["reference_audio_muted"]
    assert ref["status"] == "fail"
    assert ref["actual"] == ["A4 REF 2pop scratch"]
    assert "Mute" in ref["fix_hint"]

    assert by_key["video_track_count"]["status"] == "pass"
    assert by_key["audio_track_count"]["status"] == "pass"


# --------------------------------------------------------------------------- #
# S8 — sequence --fix writes a corrected, round-tripping OTIO.
# --------------------------------------------------------------------------- #


def test_S8_sequence_fix_roundtrip(tmp_path: Path) -> None:
    fixed = tmp_path / "fixed.otio"

    first = run_cli(
        "sequence",
        "examples/seq_netflix_fail.otio",
        "--spec",
        "netflix-imf",
        "--fix",
        str(fixed),
        "--json",
    )
    # The input verdict is unchanged by --fix: still non-conformant (exit 1).
    assert first.returncode == 1, first.stderr
    assert fixed.exists(), "fixed.otio was not written"

    # Re-parses cleanly via opentimelineio (valid OTIO) and the reference track is
    # natively disabled while the other audio tracks remain enabled.
    import opentimelineio as otio

    tl = otio.adapters.read_from_file(str(fixed))
    audio_enabled = {
        tr.name: tr.enabled for tr in tl.tracks if tr.kind == otio.schema.TrackKind.Audio
    }
    assert audio_enabled.get("A4 REF 2pop scratch") is False, audio_enabled
    for name, enabled in audio_enabled.items():
        if name != "A4 REF 2pop scratch":
            assert enabled is True, (name, enabled)

    # Re-check: mute took effect (reference PASS) but the under-length slate is only
    # flagged, never fabricated (slate_duration still FAIL) -> exit 1, 4 pass/1 fail.
    recheck = run_cli("sequence", str(fixed), "--spec", "netflix-imf", "--json")
    assert recheck.returncode == 1, recheck.stderr
    robj = parse_single_json(recheck.stdout)
    assert robj["counts"] == {"pass": 4, "fail": 1, "unknown": 0}
    rkey = {r["key"]: r for r in robj["results"]}
    assert rkey["reference_audio_muted"]["status"] == "pass"
    assert rkey["slate_duration"]["status"] == "fail"


# --------------------------------------------------------------------------- #
# S9 — optional model seam: ambiguous role inference cannot change the verdict.
#       Hermetic library scenario driven only by replykit.ScriptedModel.
# --------------------------------------------------------------------------- #


def test_S9_model_seam_ai_discipline() -> None:
    from replykit import ScriptedModel

    import conforma

    tl = conforma.read_timeline("tests/sequence/fixtures/seq_2pop_ambiguous.otio")
    layout = conforma.extract_layout(tl, source="amb.otio")
    spec = conforma.load_seq_preset("netflix-imf")

    # Exactly one ambiguous track: the bare 'Stem Foxtrot'. The keyworded tracks
    # resolve deterministically (REF 2pop temp->reference, DX->dialogue, M&E->me).
    audio_roles = {t.name: t.role for t in layout.tracks if t.kind == "audio"}
    unknown = {name for name, role in audio_roles.items() if role == "unknown"}
    assert unknown == {"Stem Foxtrot"}, audio_roles
    assert audio_roles["REF 2pop temp"] == "reference"
    assert audio_roles["DX"] == "dialogue"
    assert audio_roles["M&E"] == "me"

    # No-model deterministic run.
    det = conforma.SequenceConformanceAgent().check(spec, layout)

    # With-model run: deliberately WRONG role 'music' for the ambiguous stem, then a
    # narrative. loop=True keeps the script from exhausting regardless of step count.
    wrong_model = ScriptedModel(["music"] * 8 + ["narrative"], loop=True)
    mod = conforma.SequenceConformanceAgent(wrong_model).check(spec, layout)

    det_map = {r.key: (r.status, r.actual) for r in det.results}
    mod_map = {r.key: (r.status, r.actual) for r in mod.results}
    # The model cannot change any deterministic verdict (status + actual) even with
    # a wrong answer.
    assert det_map == mod_map
    assert det.conformant == mod.conformant

    # AI discipline on the narrative seam: no model -> no narrative; with model ->
    # a non-empty narrative over the already-computed report.
    assert det.llm_summary == ""
    assert isinstance(mod.llm_summary, str) and mod.llm_summary != ""

    # A further run classifying the ambiguous stem as 'reference' still does not flip
    # the already-resolved REF 2pop temp track away from its deterministic outcome:
    # reference_audio_muted stays FAIL and REF 2pop temp stays in the failing list.
    ref_model = ScriptedModel(["reference"] * 8 + ["narrative"], loop=True)
    mod2 = conforma.SequenceConformanceAgent(ref_model).check(spec, layout)
    det_ref = next(r for r in det.results if r.key == "reference_audio_muted")
    mod2_ref = next(r for r in mod2.results if r.key == "reference_audio_muted")
    assert det_ref.status == mod2_ref.status  # deterministic FAIL is preserved
    assert "REF 2pop temp" in list(det_ref.actual)
    assert "REF 2pop temp" in list(mod2_ref.actual)


# --------------------------------------------------------------------------- #
# S10 — Markdown --report is a stable, structured CI artifact.
# --------------------------------------------------------------------------- #


def test_S10_markdown_report(tmp_path: Path) -> None:
    report = tmp_path / "r.md"
    proc = run_cli(
        "check",
        "tests/fixtures/ffprobe_netflix_fail.json",
        "--spec",
        "netflix-hd",
        "--report",
        str(report),
        "--json",
    )
    assert proc.returncode == 1, proc.stderr
    assert report.exists()

    text = report.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "# Conformance report: Netflix HD ProRes (approx.) v1.0"
    assert "- **Verdict:** ❌ NON-CONFORMANT" in text
    assert "- **Counts:** 3 pass / 6 fail / 0 unknown" in text
    assert "## Results" in text
    assert "| Requirement | Status | Expected | Actual | Detail |" in text
    assert "## Suggested fixes" in text
    # Exactly 6 fenced ```ffmpeg code blocks (one per must failure).
    assert text.count("```ffmpeg") == 6


# --------------------------------------------------------------------------- #
# S11 — unknown spec is a clean usage error (exit 2).
# --------------------------------------------------------------------------- #


def test_S11_unknown_spec_usage_error() -> None:
    proc = run_cli(
        "check", "examples/probe_netflix_pass.json", "--spec", "does-not-exist", "--json"
    )
    assert proc.returncode == 2, proc.stderr
    obj = parse_single_json(proc.stdout)

    assert set(obj.keys()) == {"error"}
    msg = obj["error"]
    assert "preset" in msg.lower()
    assert "netflix-hd" in msg
    assert "ebu-broadcast" in msg
    for forbidden in ("conformant", "counts", "results"):
        assert forbidden not in obj


# --------------------------------------------------------------------------- #
# S12 — spec with an unknown rule key is an authoring error (exit 2).
# --------------------------------------------------------------------------- #

BAD_YAML = """\
name: Bad Spec
version: "1.0"
requirements:
  - key: not_a_real_rule
    expected: 1
"""


def test_S12_unknown_rule_key_authoring_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(BAD_YAML, encoding="utf-8")

    proc = run_cli("show", str(bad), "--json")
    assert proc.returncode == 2, proc.stderr
    obj = parse_single_json(proc.stdout)

    assert set(obj.keys()) == {"error"}
    msg = obj["error"]
    assert "not_a_real_rule" in msg
    # Enumerates the known rule keys (every one of the nine is named).
    for key in KNOWN_RULE_KEYS:
        assert key in msg, (key, msg)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
