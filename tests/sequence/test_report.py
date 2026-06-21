"""Unit tests for the sequence report projections (:mod:`conforma.sequence.report`)."""

from __future__ import annotations

import json
from typing import Any

from conforma.sequence.agent import SequenceConformanceAgent
from conforma.sequence.report import (
    render_sequence_report,
    render_sequence_report_markdown,
    sequence_report_to_dict,
)


def _report(layout_fixture: Any, netflix_imf_spec: Any, name: str):
    layout = layout_fixture(name)
    return SequenceConformanceAgent().check(netflix_imf_spec, layout)


def test_report_to_dict_stable_top_level_keys(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    report = _report(layout_fixture, netflix_imf_spec, "seq_netflix_fail.otio")
    d = sequence_report_to_dict(report)
    assert set(d) >= {"spec", "sequence", "conformant", "counts", "llm_summary", "results"}
    assert d["spec"]["name"] == report.spec_name
    assert d["spec"]["version"] == report.spec_version
    assert d["sequence"]["source"] == report.sequence_source
    assert d["conformant"] is False
    assert isinstance(d["results"], list)


def test_report_to_dict_result_shape(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    report = _report(layout_fixture, netflix_imf_spec, "seq_netflix_fail.otio")
    d = sequence_report_to_dict(report)
    for entry in d["results"]:
        assert set(entry) >= {
            "key",
            "status",
            "expected",
            "actual",
            "message",
            "severity",
            "fix_hint",
        }


def test_report_to_dict_json_safe(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    report = _report(layout_fixture, netflix_imf_spec, "seq_netflix_fail.otio")
    payload = json.dumps(sequence_report_to_dict(report))
    assert json.loads(payload)["conformant"] is False


def test_render_no_ansi_when_color_false(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    report = _report(layout_fixture, netflix_imf_spec, "seq_netflix_fail.otio")
    text = render_sequence_report(report, color=False)
    assert "\x1b[" not in text  # no ANSI escapes
    assert "NON-CONFORMANT" in text
    # Fix hints surfaced under failures.
    assert "Fix hints:" in text


def test_render_is_deterministic(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    report = _report(layout_fixture, netflix_imf_spec, "seq_netflix_fail.otio")
    a = render_sequence_report(report, color=False)
    b = render_sequence_report(report, color=False)
    assert a == b


def test_render_pass_is_conformant(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    report = _report(layout_fixture, netflix_imf_spec, "seq_netflix_pass.otio")
    text = render_sequence_report(report, color=False)
    assert "CONFORMANT" in text
    assert "NON-CONFORMANT" not in text


def test_markdown_is_deterministic_and_diffable(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    report = _report(layout_fixture, netflix_imf_spec, "seq_netflix_fail.otio")
    a = render_sequence_report_markdown(report)
    b = render_sequence_report_markdown(report)
    assert a == b
    assert a.startswith("# Sequence conformance report:")
    assert "## Results" in a
    assert "## Fix hints" in a
    assert "NON-CONFORMANT" in a
    # Each result key appears as a table row.
    for r in report.results:
        assert r.key in a


def test_markdown_golden_pass(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    report = _report(layout_fixture, netflix_imf_spec, "seq_netflix_pass.otio")
    md = render_sequence_report_markdown(report)
    expected = (
        "# Sequence conformance report: Netflix IMF Editorial v1.0\n"
        "\n"
        "- **Sequence:** `seq_netflix_pass.otio`\n"
        "- **Verdict:** ✅ CONFORMANT\n"
        "- **Counts:** 5 pass / 0 fail / 0 unknown\n"
        "\n"
        "## Results\n"
        "\n"
        "| Rule | Status | Expected | Actual | Detail |\n"
        "| --- | --- | --- | --- | --- |\n"
    )
    assert md.startswith(expected)
    # A conformant report has no Fix hints section.
    assert "## Fix hints" not in md


def test_render_does_not_change_verdict(layout_fixture: Any, netflix_imf_spec: Any) -> None:
    report = _report(layout_fixture, netflix_imf_spec, "seq_netflix_fail.otio")
    before = report.conformant
    render_sequence_report(report, color=False)
    render_sequence_report_markdown(report)
    sequence_report_to_dict(report)
    assert report.conformant == before


def test_markdown_includes_llm_summary_when_present(
    layout_fixture: Any, netflix_imf_spec: Any
) -> None:
    from dataclasses import replace

    report = _report(layout_fixture, netflix_imf_spec, "seq_netflix_fail.otio")
    report = replace(report, llm_summary="A human-readable audit narrative.")
    md = render_sequence_report_markdown(report)
    assert "## Summary" in md
    assert "A human-readable audit narrative." in md
    text = render_sequence_report(report, color=False)
    assert "A human-readable audit narrative." in text
