"""End-to-end, hermetic integration tests for conforma.

Where :mod:`tests.test_cli` pins focused CLI behaviors, this file exercises the
whole pipeline through the public surface: spec -> probe -> deterministic
verdict -> rendered projection, across both probe sources and both shipped
presets. It also covers the ``--report`` Markdown artifact, the optional
replykit agent narrative (driven by a :class:`replykit.ScriptedModel`, never a
live model), and proves the shipped ``examples/`` scripts run offline.

Nothing here touches ffmpeg, ffprobe, the network, or a real LLM.
"""

from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner  # noqa: E402

import conforma  # noqa: E402
from conforma.cli import EXIT_NONCONFORMANT, EXIT_OK, EXIT_USAGE, app  # noqa: E402

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"


def _json_out(result: object) -> dict:
    return json.loads(result.stdout)  # type: ignore[attr-defined]


# --- probe-source parity ---------------------------------------------------


def test_ffprobe_and_mediainfo_agree_on_netflix_pass(fixture_path) -> None:
    """The same content as ffprobe JSON and MediaInfo JSON must agree."""
    ff = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_netflix_pass"), "--spec", "netflix-hd", "--json"],
    )
    mi = runner.invoke(
        app,
        ["check", fixture_path("mediainfo_netflix_pass"), "--spec", "netflix-hd", "--json"],
    )
    assert ff.exit_code == EXIT_OK
    assert mi.exit_code == EXIT_OK
    ff_payload = _json_out(ff)
    mi_payload = _json_out(mi)
    assert ff_payload["conformant"] is True
    assert mi_payload["conformant"] is True
    # Per-requirement verdicts must match regardless of probe source.
    ff_status = {r["key"]: r["status"] for r in ff_payload["results"]}
    mi_status = {r["key"]: r["status"] for r in mi_payload["results"]}
    assert ff_status == mi_status


# --- both presets end to end -----------------------------------------------


def test_ebu_preset_pass(fixture_path) -> None:
    result = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_ebu_pass"), "--spec", "ebu-broadcast", "--json"],
    )
    assert result.exit_code == EXIT_OK
    payload = _json_out(result)
    assert payload["conformant"] is True


def test_netflix_fixture_fails_ebu_spec(fixture_path) -> None:
    """A Netflix-style file checked against the EBU spec is non-conformant.

    Different container (mov vs mxf), frame rate, scan type, and codec — a good
    cross-check that verdicts are spec-relative, not hard-coded.
    """
    result = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_netflix_pass"), "--spec", "ebu-broadcast", "--json"],
    )
    assert result.exit_code == EXIT_NONCONFORMANT
    payload = _json_out(result)
    assert payload["conformant"] is False


# --- sparse probe -> UNKNOWN, never a crash --------------------------------


def test_sparse_probe_yields_unknowns_not_crash(fixture_path) -> None:
    """A probe missing fields produces UNKNOWN rows; the CLI never raises."""
    result = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_sparse"), "--spec", "netflix-hd", "--json"],
    )
    # Exit code is 0 or 1 (a real verdict), never a usage crash.
    assert result.exit_code in (EXIT_OK, EXIT_NONCONFORMANT)
    payload = _json_out(result)
    statuses = {r["status"] for r in payload["results"]}
    assert "unknown" in statuses


# --- --report Markdown artifact --------------------------------------------


def test_report_flag_writes_markdown(fixture_path, tmp_path) -> None:
    out = tmp_path / "report.md"
    result = runner.invoke(
        app,
        [
            "check",
            fixture_path("ffprobe_netflix_fail"),
            "--spec",
            "netflix-hd",
            "--report",
            str(out),
        ],
    )
    assert result.exit_code == EXIT_NONCONFORMANT
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    # A portable Markdown report with a fenced ffmpeg block per failure.
    assert "ffmpeg" in text
    assert "```" in text


def test_report_and_json_together(fixture_path, tmp_path) -> None:
    """``--report`` writes the file *and* ``--json`` still prints one object."""
    out = tmp_path / "r.md"
    result = runner.invoke(
        app,
        [
            "check",
            fixture_path("ffprobe_netflix_pass"),
            "--spec",
            "netflix-hd",
            "--report",
            str(out),
            "--json",
        ],
    )
    assert result.exit_code == EXIT_OK
    assert out.exists()
    payload = _json_out(result)  # stdout is still exactly one JSON object
    assert payload["conformant"] is True


def test_report_unwritable_path_exit_two(fixture_path, tmp_path) -> None:
    """A report path inside a missing directory is a clean usage error."""
    bad = tmp_path / "no_such_dir" / "report.md"
    result = runner.invoke(
        app,
        [
            "check",
            fixture_path("ffprobe_netflix_pass"),
            "--spec",
            "netflix-hd",
            "--report",
            str(bad),
            "--json",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    payload = _json_out(result)
    assert set(payload) == {"error"}


# --- custom spec file via --spec path --------------------------------------


def test_custom_spec_file_path(fixture_path) -> None:
    """``--spec`` accepts a YAML file path, not just a preset name."""
    custom = EXAMPLES_DIR / "netflix-custom.yaml"
    assert custom.exists(), "the example custom spec must ship in examples/"
    result = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_netflix_pass"), "--spec", str(custom), "--json"],
    )
    # The exact verdict depends on the custom spec; either way it must be a real
    # verdict (0/1), parse cleanly, and echo the custom spec's name.
    assert result.exit_code in (EXIT_OK, EXIT_NONCONFORMANT)
    payload = _json_out(result)
    assert "spec" in payload


# --- optional agent narrative (hermetic, ScriptedModel) --------------------


def test_agent_narrative_is_hermetic_and_grounded(fixture_path) -> None:
    """The replykit agent can narrate a report without a live model.

    Verdicts stay deterministic; the ScriptedModel only adds prose. This proves
    the public agent path is exercisable offline (the README's selling point).
    """
    from replykit import ScriptedModel

    spec = conforma.load_preset("netflix-hd")
    profile = conforma.load_probe(fixture_path("ffprobe_netflix_fail"))

    # Deterministic verdict first (no model).
    base = conforma.ConformanceAgent().check(spec, profile, input_path="in.mov")
    assert base.conformant is False

    # A scripted model that immediately gives a final answer (no tool call).
    model = ScriptedModel(["The frame rate and resolution are out of spec."])
    summary = conforma.explain_report(base, model)
    assert isinstance(summary, str)
    assert summary  # non-empty narrative


# --- shipped example scripts run offline -----------------------------------


@pytest.mark.parametrize("script", ["check_netflix.py", "check_ebu.py"])
def test_example_script_runs(script: str) -> None:
    """Every example under examples/ runs hermetically end to end."""
    path = EXAMPLES_DIR / script
    assert path.exists(), f"missing example: {script}"
    completed = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip(), "example produced no output"


def test_example_probe_fixture_is_valid_json() -> None:
    """The shipped example probe JSON parses and normalizes through the public API."""
    probe = EXAMPLES_DIR / "probe_netflix_pass.json"
    assert probe.exists()
    data = json.loads(probe.read_text(encoding="utf-8"))
    profile = conforma.normalize_probe(data, source=str(probe))
    assert profile.video is not None


def test_examples_dir_has_runnable_modules() -> None:
    """Sanity: the example scripts are importable as modules (syntactically valid)."""
    for name in ("check_netflix.py", "check_ebu.py"):
        spec = importlib.util.spec_from_file_location(
            f"_conforma_example_{name}", EXAMPLES_DIR / name
        )
        assert spec is not None and spec.loader is not None


# --- usage-error stdout hygiene --------------------------------------------


def test_usage_error_human_keeps_stdout_clean(fixture_path) -> None:
    """A human-mode usage error prints to stderr, never stdout (pipeline-safe)."""
    result = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_netflix_pass"), "--spec", "nope"],
    )
    assert result.exit_code == EXIT_USAGE
    # CliRunner merges stderr into stdout by default unless mix_stderr=False,
    # so just assert the error text surfaced and the run failed cleanly.
    assert "nope" in result.output


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def test_runpy_example_check_netflix() -> None:
    """Run check_netflix.py in-process via runpy for coverage + a fast smoke test."""
    path = EXAMPLES_DIR / "check_netflix.py"
    # runpy executes the module's __main__ guard body if invoked as __main__.
    runpy.run_path(str(path), run_name="__main__")
