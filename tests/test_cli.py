"""Hermetic unit tests for the conforma CLI surface.

These drive the real command surface via Typer's :class:`CliRunner` and assert on
the ``--json`` payloads (the automation contract) and the exit-code policy
(``0`` conformant / ``1`` non-conformant / ``2`` usage error). Everything runs
offline off committed fixture JSON and shipped presets — no ffmpeg, no ffprobe,
no network, no live LLM.

The companion :mod:`tests.test_cli_integration` covers richer end-to-end flows
(MediaInfo parity, ``--report`` artifacts, auto-probe gating). This file pins the
focused behaviors: helper resolvers, the JSON contract, and error handling.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner  # noqa: E402

import conforma  # noqa: E402
from conforma import cli  # noqa: E402
from conforma.cli import (  # noqa: E402
    EXIT_NONCONFORMANT,
    EXIT_OK,
    EXIT_USAGE,
    _looks_like_json,
    _resolve_profile,
    _resolve_spec,
    app,
)

runner = CliRunner()


def _json_out(result: object) -> dict:
    """Parse the single JSON object a ``--json`` invocation prints to stdout."""
    return json.loads(result.stdout)  # type: ignore[attr-defined]


# --- top-level help --------------------------------------------------------


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    # no_args_is_help: Typer renders usage; the exit code varies by version.
    assert "Usage" in result.stdout or "Commands" in result.stdout


def test_help_lists_all_three_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == EXIT_OK
    for command in ("check", "presets", "show"):
        assert command in result.stdout


def test_every_command_supports_json_flag() -> None:
    """The automation contract: each command advertises ``--json`` in its help."""
    for command in ("check", "presets", "show"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == EXIT_OK
        assert "--json" in result.stdout


# --- _looks_like_json heuristic --------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("probe.json", True),
        ("PROBE.JSON", True),
        ("/abs/path/ffprobe_out.json", True),
        ("master.mov", False),
        ("clip.mxf", False),
        ("no_extension", False),
    ],
)
def test_looks_like_json(path: str, expected: bool) -> None:
    assert _looks_like_json(path) is expected


# --- _resolve_spec ---------------------------------------------------------


def test_resolve_spec_unknown_name_raises_specerror() -> None:
    with pytest.raises(conforma.SpecError):
        _resolve_spec("does-not-exist")


def test_resolve_spec_preset_name_wins_over_cwd_file(tmp_path, monkeypatch) -> None:
    """A bare preset name resolves to the shipped preset, not a same-named file."""
    # Even if a stray 'netflix-hd' file exists in cwd, the preset takes precedence.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "netflix-hd").write_text("garbage: not a spec\n", encoding="utf-8")
    spec = _resolve_spec("netflix-hd")
    assert spec.name  # a real, validated preset loaded — no YAML parse error


# --- _resolve_profile gating -----------------------------------------------


def test_resolve_profile_non_json_without_ffprobe_raises(monkeypatch) -> None:
    """A media path with ffprobe absent is a usage error, not a silent probe."""
    monkeypatch.setattr(conforma, "ffprobe_available", lambda: False)
    with pytest.raises(conforma.ProbeError):
        _resolve_profile("master.mov")


def test_resolve_profile_non_json_with_ffprobe_calls_probe_media(monkeypatch) -> None:
    """When ffprobe is on PATH, a media path is auto-probed (no JSON suffix needed)."""
    sentinel = conforma.MediaProfile(container="mov", source="ffprobe")
    monkeypatch.setattr(conforma, "ffprobe_available", lambda: True)

    called: dict[str, str] = {}

    def fake_probe_media(path: str, **_kw: object) -> conforma.MediaProfile:
        called["path"] = path
        return sentinel

    monkeypatch.setattr(conforma, "probe_media", fake_probe_media)
    profile = _resolve_profile("master.mov")
    assert profile is sentinel
    assert called["path"] == "master.mov"


def test_resolve_profile_json_path_loads_probe(monkeypatch) -> None:
    """A ``*.json`` path is always loaded as probe JSON, ffprobe irrelevant."""
    sentinel = conforma.MediaProfile(container="mov", source="x.json")
    # ffprobe present, but the .json suffix must short-circuit to load_probe.
    monkeypatch.setattr(conforma, "ffprobe_available", lambda: True)

    def fake_load_probe(path: str) -> conforma.MediaProfile:
        assert path == "x.json"
        return sentinel

    def boom(*_a: object, **_k: object) -> object:
        raise AssertionError("probe_media must not be called for a .json path")

    monkeypatch.setattr(conforma, "load_probe", fake_load_probe)
    monkeypatch.setattr(conforma, "probe_media", boom)
    assert _resolve_profile("x.json") is sentinel


# --- check: exit-code contract ---------------------------------------------


def test_check_pass_exit_zero(fixture_path) -> None:
    result = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_netflix_pass"), "--spec", "netflix-hd"],
    )
    assert result.exit_code == EXIT_OK


def test_check_fail_exit_one(fixture_path) -> None:
    result = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_netflix_fail"), "--spec", "netflix-hd"],
    )
    assert result.exit_code == EXIT_NONCONFORMANT


def test_check_bad_spec_exit_two(fixture_path) -> None:
    result = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_netflix_pass"), "--spec", "no-such-preset"],
    )
    assert result.exit_code == EXIT_USAGE


def test_check_missing_probe_file_exit_two() -> None:
    result = runner.invoke(
        app,
        ["check", "does_not_exist.json", "--spec", "netflix-hd"],
    )
    assert result.exit_code == EXIT_USAGE


# --- check: --json automation contract -------------------------------------


def test_check_json_is_single_object_and_matches_report_to_dict(fixture_path) -> None:
    result = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_netflix_pass"), "--spec", "netflix-hd", "--json"],
    )
    assert result.exit_code == EXIT_OK
    payload = _json_out(result)  # raises if stdout is not exactly one JSON object
    # Top-level shape is the documented --json contract.
    assert payload["conformant"] is True
    assert "spec" in payload
    assert "media" in payload
    assert "counts" in payload
    assert isinstance(payload["results"], list)
    assert payload["results"], "a non-empty per-requirement results list"
    for item in payload["results"]:
        assert {"key", "status", "expected", "actual", "message"} <= set(item)


def test_check_json_failpath_carries_fix_commands(fixture_path) -> None:
    result = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_netflix_fail"), "--spec", "netflix-hd", "--json"],
    )
    assert result.exit_code == EXIT_NONCONFORMANT
    payload = _json_out(result)
    assert payload["conformant"] is False
    fails = [r for r in payload["results"] if r["status"] == "fail"]
    assert fails, "the fail fixture must produce at least one FAIL"
    # Every deterministic failure surfaces a non-empty ffmpeg fix command.
    assert all(r["fix_command"] for r in fails)


def test_check_json_error_is_single_error_object(fixture_path) -> None:
    """Even on failure, --json prints exactly one JSON object (``{"error": ...}``)."""
    result = runner.invoke(
        app,
        ["check", fixture_path("ffprobe_netflix_pass"), "--spec", "nope", "--json"],
    )
    assert result.exit_code == EXIT_USAGE
    payload = _json_out(result)
    assert set(payload) == {"error"}
    assert "nope" in payload["error"]


# --- presets ---------------------------------------------------------------


def test_presets_json_lists_shipped_presets() -> None:
    result = runner.invoke(app, ["presets", "--json"])
    assert result.exit_code == EXIT_OK
    payload = _json_out(result)
    names = {p["name"] for p in payload["presets"]}
    assert {"netflix-hd", "ebu-broadcast"} <= names
    for item in payload["presets"]:
        assert item["requirements"] > 0
        assert item["spec_name"]


def test_presets_human_render_mentions_presets() -> None:
    result = runner.invoke(app, ["presets"])
    assert result.exit_code == EXIT_OK
    assert "netflix-hd" in result.stdout
    assert "ebu-broadcast" in result.stdout


# --- show ------------------------------------------------------------------


def test_show_preset_json_roundtrips_as_dict() -> None:
    result = runner.invoke(app, ["show", "netflix-hd", "--json"])
    assert result.exit_code == EXIT_OK
    payload = _json_out(result)
    expected = conforma.load_preset("netflix-hd").as_dict()
    assert payload == expected


def test_show_unknown_spec_exit_two_json() -> None:
    result = runner.invoke(app, ["show", "ghost-spec", "--json"])
    assert result.exit_code == EXIT_USAGE
    payload = _json_out(result)
    assert set(payload) == {"error"}


def test_show_human_render_lists_requirement_keys() -> None:
    result = runner.invoke(app, ["show", "netflix-hd"])
    assert result.exit_code == EXIT_OK
    # A couple of stable requirement keys must show up in the rendered table.
    assert "resolution" in result.stdout
    assert "frame_rate" in result.stdout


# --- module wiring ---------------------------------------------------------


def test_main_is_callable() -> None:
    assert callable(cli.main)


def test_main_dispatches_to_app(monkeypatch) -> None:
    """``main()`` is the console-script entry point and just invokes the Typer app."""
    called: list[bool] = []
    monkeypatch.setattr(cli, "app", lambda: called.append(True))
    cli.main()
    assert called == [True]


def test_cli_imports_only_public_api() -> None:
    """The CLI must build on the package root, never private submodule internals."""
    import inspect

    source = inspect.getsource(cli)
    # No `from conforma.<submodule> import` lines (only `import conforma` allowed).
    assert "from conforma." not in source
    assert "conforma._" not in source
