"""Hermetic unit tests for the ``conforma sequence`` CLI subcommand.

These drive the real command surface via Typer's :class:`CliRunner` and assert on
the ``--json`` payloads (the automation contract) and the exit-code policy
(``0`` conformant / ``1`` non-conformant / ``2`` usage error) — the same contract
as ``check``. Everything runs offline off the committed ``examples/*.otio``
timelines and the shipped ``netflix-imf`` preset: no NLE, no network, no live LLM.
OTIO's ``otio_json`` adapter ships with opentimelineio, so the ``.otio`` path
needs no optional plugin.

The companion :mod:`tests.test_sequence_examples` covers richer end-to-end flows
(``--fix`` round-trips, the example script, the agent narrative). This file pins
the focused CLI behaviors: the spec resolver, the JSON contract, ``--report`` /
``--fix`` wiring, and error handling.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")
pytest.importorskip("opentimelineio")

from typer.testing import CliRunner  # noqa: E402

import conforma  # noqa: E402
from conforma.cli import (  # noqa: E402
    EXIT_NONCONFORMANT,
    EXIT_OK,
    EXIT_USAGE,
    _resolve_seq_spec,
    app,
)

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"
PASS_SEQ = EXAMPLES_DIR / "seq_netflix_pass.otio"
FAIL_SEQ = EXAMPLES_DIR / "seq_netflix_fail.otio"


def _json_out(result: object) -> dict:
    """Parse the single JSON object a ``--json`` invocation prints to stdout."""
    return json.loads(result.stdout)  # type: ignore[attr-defined]


# --- help / discovery ------------------------------------------------------


def test_sequence_command_listed_in_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == EXIT_OK
    assert "sequence" in result.stdout


def test_example_timelines_exist() -> None:
    """The committed example timelines the tests drive must ship."""
    assert PASS_SEQ.exists(), "examples/seq_netflix_pass.otio must ship"
    assert FAIL_SEQ.exists(), "examples/seq_netflix_fail.otio must ship"


# --- spec resolver ---------------------------------------------------------


def test_resolve_seq_spec_preset_name() -> None:
    spec = _resolve_seq_spec("netflix-imf")
    assert isinstance(spec, conforma.DeliverySpec)
    assert spec.source == "netflix-imf"


def test_resolve_seq_spec_unknown_raises() -> None:
    with pytest.raises(conforma.SequenceSpecError):
        _resolve_seq_spec("not-a-real-preset")


def test_resolve_seq_spec_yaml_path(tmp_path) -> None:
    spec_file = tmp_path / "house.yaml"
    spec_file.write_text(
        "name: House Spec\nversion: '2'\nsequence:\n  expected_video_tracks: 1\n",
        encoding="utf-8",
    )
    spec = _resolve_seq_spec(str(spec_file))
    assert spec.name == "House Spec"
    assert spec.expected_video_tracks == 1


# --- the JSON contract: PASS / FAIL ----------------------------------------


def test_sequence_pass_json_exit_zero() -> None:
    result = runner.invoke(app, ["sequence", str(PASS_SEQ), "--spec", "netflix-imf", "--json"])
    assert result.exit_code == EXIT_OK
    payload = _json_out(result)
    assert payload["conformant"] is True
    assert payload["spec"]["name"] == "Netflix IMF Editorial"
    assert payload["sequence"]["source"].endswith("seq_netflix_pass.otio")
    # The documented result shape.
    keys = {r["key"] for r in payload["results"]}
    assert {"slate_present", "slate_duration", "reference_audio_muted"} <= keys
    for r in payload["results"]:
        assert set(r) == {
            "key",
            "status",
            "expected",
            "actual",
            "message",
            "severity",
            "fix_hint",
        }


def test_sequence_fail_json_exit_one() -> None:
    result = runner.invoke(app, ["sequence", str(FAIL_SEQ), "--spec", "netflix-imf", "--json"])
    assert result.exit_code == EXIT_NONCONFORMANT
    payload = _json_out(result)
    assert payload["conformant"] is False
    by_key = {r["key"]: r for r in payload["results"]}
    # The fail fixture is a 2 s slate with a still-enabled reference track.
    assert by_key["slate_duration"]["status"] == "fail"
    assert by_key["reference_audio_muted"]["status"] == "fail"
    # Failures carry a deterministic fix hint.
    assert by_key["slate_duration"]["fix_hint"]
    assert by_key["reference_audio_muted"]["fix_hint"]


def test_sequence_json_is_exactly_one_object() -> None:
    """``--json`` prints exactly one JSON object and nothing else (pipeline-safe)."""
    result = runner.invoke(app, ["sequence", str(PASS_SEQ), "--spec", "netflix-imf", "--json"])
    # json.loads over the whole stdout must succeed -> a single object, no extras.
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)


# --- human (non-JSON) rendering --------------------------------------------


def test_sequence_human_render_pass() -> None:
    result = runner.invoke(app, ["sequence", str(PASS_SEQ), "--spec", "netflix-imf"])
    assert result.exit_code == EXIT_OK
    assert "CONFORMANT" in result.stdout
    assert "Netflix IMF Editorial" in result.stdout


def test_sequence_human_render_fail_shows_fix_hints() -> None:
    result = runner.invoke(app, ["sequence", str(FAIL_SEQ), "--spec", "netflix-imf"])
    assert result.exit_code == EXIT_NONCONFORMANT
    assert "NON-CONFORMANT" in result.stdout
    assert "Fix hints" in result.stdout


# --- --report and --fix wiring ---------------------------------------------


def test_sequence_report_writes_markdown(tmp_path) -> None:
    out = tmp_path / "seq_report.md"
    result = runner.invoke(
        app,
        ["sequence", str(FAIL_SEQ), "--spec", "netflix-imf", "--report", str(out)],
    )
    assert result.exit_code == EXIT_NONCONFORMANT
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Sequence conformance report" in text
    assert "slate_duration" in text


def test_sequence_fix_writes_corrected_timeline(tmp_path) -> None:
    out = tmp_path / "fixed.otio"
    result = runner.invoke(
        app,
        ["sequence", str(FAIL_SEQ), "--spec", "netflix-imf", "--fix", str(out), "--json"],
    )
    assert result.exit_code == EXIT_NONCONFORMANT
    assert out.exists()
    # The corrected timeline mutes the reference audio track.
    fixed = conforma.read_timeline(str(out))
    layout = conforma.extract_layout(fixed, source=str(out))
    ref_tracks = [t for t in layout.tracks if t.role == "reference"]
    assert ref_tracks, "the fail fixture has a reference track"
    assert all(t.enabled is False for t in ref_tracks)


def test_sequence_report_and_fix_and_json_together(tmp_path) -> None:
    """``--report`` + ``--fix`` write files *and* ``--json`` prints one object."""
    report_out = tmp_path / "r.md"
    fix_out = tmp_path / "f.otio"
    result = runner.invoke(
        app,
        [
            "sequence",
            str(FAIL_SEQ),
            "--spec",
            "netflix-imf",
            "--report",
            str(report_out),
            "--fix",
            str(fix_out),
            "--json",
        ],
    )
    assert result.exit_code == EXIT_NONCONFORMANT
    assert report_out.exists() and fix_out.exists()
    payload = _json_out(result)  # stdout is still exactly one JSON object
    assert payload["conformant"] is False


# --- error handling --------------------------------------------------------


def test_sequence_unknown_spec_exit_two_json() -> None:
    result = runner.invoke(app, ["sequence", str(PASS_SEQ), "--spec", "nope", "--json"])
    assert result.exit_code == EXIT_USAGE
    payload = _json_out(result)
    assert set(payload) == {"error"}
    assert "nope" in payload["error"]


def test_sequence_unsupported_suffix_exit_two(tmp_path) -> None:
    bad = tmp_path / "timeline.weird"
    bad.write_text("not a timeline", encoding="utf-8")
    result = runner.invoke(app, ["sequence", str(bad), "--spec", "netflix-imf", "--json"])
    assert result.exit_code == EXIT_USAGE
    payload = _json_out(result)
    assert set(payload) == {"error"}


def test_sequence_missing_file_exit_two(tmp_path) -> None:
    missing = tmp_path / "nope.otio"
    result = runner.invoke(app, ["sequence", str(missing), "--spec", "netflix-imf", "--json"])
    assert result.exit_code == EXIT_USAGE
    payload = _json_out(result)
    assert set(payload) == {"error"}


def test_sequence_report_unwritable_path_exit_two(tmp_path) -> None:
    bad = tmp_path / "no_such_dir" / "report.md"
    result = runner.invoke(
        app,
        [
            "sequence",
            str(PASS_SEQ),
            "--spec",
            "netflix-imf",
            "--report",
            str(bad),
            "--json",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    payload = _json_out(result)
    assert set(payload) == {"error"}
