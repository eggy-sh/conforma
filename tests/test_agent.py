"""Unit tests for the replykit agent layer (:mod:`conforma.agent`)."""

from __future__ import annotations

from typing import Any

from replykit import ScriptedModel

from conforma.agent import ConformanceAgent, build_fix_registry, explain_report
from conforma.fixes import suggest_fix
from conforma.models import CheckStatus
from conforma.probe import normalize_probe
from conforma.rules import check_all
from conforma.spec import load_preset


def test_deterministic_check_no_model_populates_fixes(
    ffprobe_netflix_fail: dict[str, Any],
) -> None:
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_fail)
    report = ConformanceAgent(model=None).check(spec, profile)

    assert report.llm_summary == ""
    assert report.conformant is False
    # Every FAIL carries a fix; PASS/UNKNOWN do not.
    for r in report.results:
        if r.status == CheckStatus.FAIL:
            assert r.fix_command, r.key
            assert r.fix_command.startswith("ffmpeg")
        else:
            assert r.fix_command == ""


def test_check_verdicts_identical_to_check_all(
    ffprobe_netflix_fail: dict[str, Any],
) -> None:
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_fail)
    agent_results = ConformanceAgent().check(spec, profile).results
    raw = check_all(spec.requirements, profile)
    assert [(r.key, r.status) for r in agent_results] == [(r.key, r.status) for r in raw]


def test_check_passes_input_output_paths(ffprobe_netflix_fail: dict[str, Any]) -> None:
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_fail)
    report = ConformanceAgent().check(
        spec, profile, input_path="master.mov", output_path="fixed.mov"
    )
    res_fix = next(r for r in report.results if r.key == "resolution")
    assert "master.mov" in res_fix.fix_command
    assert "fixed.mov" in res_fix.fix_command


def test_explain_report_returns_scripted_answer_and_keeps_verdict(
    ffprobe_netflix_fail: dict[str, Any],
) -> None:
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_fail)
    report = ConformanceAgent().check(spec, profile)

    model = ScriptedModel(["The file fails several Netflix requirements."])
    summary = explain_report(report, model)
    assert summary == "The file fails several Netflix requirements."
    # Verdict unchanged by explanation.
    assert report.conformant is False


def test_conformance_agent_with_model_sets_summary_not_verdict(
    ffprobe_netflix_fail: dict[str, Any],
) -> None:
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_fail)

    model = ScriptedModel(["Non-conformant: resolution and codec are wrong."])
    report = ConformanceAgent(model=model).check(spec, profile)

    assert report.llm_summary == "Non-conformant: resolution and codec are wrong."
    # Deterministic verdict preserved.
    determ = ConformanceAgent().check(spec, profile)
    assert [(r.key, r.status) for r in report.results] == [
        (r.key, r.status) for r in determ.results
    ]


def test_build_fix_registry_tools_are_grounded(
    ffprobe_netflix_fail: dict[str, Any],
) -> None:
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_fail)
    report = ConformanceAgent().check(spec, profile)
    registry = build_fix_registry(report)

    assert "suggest_fix" in registry
    assert "get_result" in registry

    from replykit import Action

    # suggest_fix(key) returns the same grounded command as conforma.fixes.
    res = report.results
    res_by_key = {r.key: r for r in res}
    fix_dispatch = registry.dispatch(Action(tool="suggest_fix", args={"key": "resolution"}, raw=""))
    assert fix_dispatch.ok
    assert fix_dispatch.value == res_by_key["resolution"].fix_command
    # And it matches a fresh deterministic computation (no fabrication).
    assert fix_dispatch.value == suggest_fix(res_by_key["resolution"])

    # get_result(key) returns the deterministic verdict, never invented.
    get_dispatch = registry.dispatch(Action(tool="get_result", args={"key": "video_codec"}, raw=""))
    assert get_dispatch.ok
    assert "video_codec" in get_dispatch.value
    assert "fail" in get_dispatch.value


def test_build_fix_registry_unknown_key_is_safe(
    ffprobe_netflix_pass: dict[str, Any],
) -> None:
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_pass)
    report = ConformanceAgent().check(spec, profile)
    registry = build_fix_registry(report)

    from replykit import Action

    fix = registry.dispatch(Action(tool="suggest_fix", args={"key": "nope"}, raw=""))
    assert fix.value == ""
    got = registry.dispatch(Action(tool="get_result", args={"key": "nope"}, raw=""))
    assert "no such requirement" in got.value
