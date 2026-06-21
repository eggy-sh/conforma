"""Unit tests for the report projections (:mod:`conforma.report`)."""

from __future__ import annotations

import json
from typing import Any

from conforma.agent import ConformanceAgent
from conforma.probe import normalize_probe
from conforma.report import render_report, render_report_markdown, report_to_dict
from conforma.spec import load_preset


def _fail_report(ffprobe_netflix_fail: dict[str, Any]):
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_fail)
    return ConformanceAgent().check(spec, profile)


def _pass_report(ffprobe_netflix_pass: dict[str, Any]):
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_pass)
    return ConformanceAgent().check(spec, profile)


def test_report_to_dict_stable_top_level_keys(ffprobe_netflix_fail: dict[str, Any]) -> None:
    report = _fail_report(ffprobe_netflix_fail)
    d = report_to_dict(report)
    assert set(d) >= {"spec", "media", "conformant", "counts", "results"}
    assert d["spec"]["name"] == report.spec_name
    assert d["media"]["source"] == report.media_source
    assert d["conformant"] is False
    assert isinstance(d["results"], list)


def test_report_to_dict_result_shape(ffprobe_netflix_fail: dict[str, Any]) -> None:
    report = _fail_report(ffprobe_netflix_fail)
    d = report_to_dict(report)
    for entry in d["results"]:
        assert set(entry) >= {
            "key",
            "status",
            "expected",
            "actual",
            "message",
            "severity",
            "fix_command",
        }


def test_report_to_dict_json_safe(ffprobe_netflix_fail: dict[str, Any]) -> None:
    report = _fail_report(ffprobe_netflix_fail)
    payload = json.dumps(report_to_dict(report))
    assert json.loads(payload)["conformant"] is False


def test_render_report_no_ansi_when_color_false(ffprobe_netflix_fail: dict[str, Any]) -> None:
    report = _fail_report(ffprobe_netflix_fail)
    text = render_report(report, color=False)
    assert "\x1b[" not in text  # no ANSI escapes
    assert "NON-CONFORMANT" in text
    assert "resolution" in text


def test_render_report_color_has_ansi(ffprobe_netflix_fail: dict[str, Any]) -> None:
    report = _fail_report(ffprobe_netflix_fail)
    text = render_report(report, color=True)
    assert "\x1b[" in text


def test_render_report_pass_is_conformant(ffprobe_netflix_pass: dict[str, Any]) -> None:
    report = _pass_report(ffprobe_netflix_pass)
    text = render_report(report, color=False)
    assert "CONFORMANT" in text
    assert "NON-CONFORMANT" not in text


def test_render_markdown_deterministic(ffprobe_netflix_fail: dict[str, Any]) -> None:
    report = _fail_report(ffprobe_netflix_fail)
    first = render_report_markdown(report)
    second = render_report_markdown(report)
    assert first == second


def test_render_markdown_has_table_and_fenced_blocks(
    ffprobe_netflix_fail: dict[str, Any],
) -> None:
    report = _fail_report(ffprobe_netflix_fail)
    md = render_report_markdown(report)
    assert "| Requirement | Status |" in md
    assert "```ffmpeg" in md
    # One fenced ffmpeg block per failure with a fix command.
    fenced = md.count("```ffmpeg")
    expected = sum(1 for r in report.failures if r.fix_command)
    assert fenced == expected
    assert expected > 0


def test_render_markdown_pass_has_no_fenced_blocks(
    ffprobe_netflix_pass: dict[str, Any],
) -> None:
    report = _pass_report(ffprobe_netflix_pass)
    md = render_report_markdown(report)
    assert "```ffmpeg" not in md
    assert "CONFORMANT" in md
