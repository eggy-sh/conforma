"""Render a :class:`SequenceReport` for humans, machines, and Markdown.

Three read-only projections of one report, mirroring :mod:`conforma.report`:

* :func:`sequence_report_to_dict` — the canonical ``--json`` shape (a pure dict
  that round-trips through ``json.dumps``).
* :func:`render_sequence_report` — a Rich table/panel string for the terminal,
  color-coded PASS/FAIL/UNKNOWN with fix hints under failures.
* :func:`render_sequence_report_markdown` — portable Markdown for ``--report``,
  deterministic and diffable.

Rendering never recomputes a verdict — what you see is exactly what
:mod:`conforma.sequence.rules` decided.
"""

from __future__ import annotations

import io
from typing import Any

from rich.console import Console
from rich.table import Table

from .models import SequenceReport

#: Rich style per status (used by :func:`render_sequence_report`).
_STATUS_STYLES: dict[str, str] = {
    "pass": "green",
    "fail": "red",
    "unknown": "yellow",
}


def sequence_report_to_dict(report: SequenceReport) -> dict[str, Any]:
    """Project a sequence report into the canonical JSON-serializable dict.

    Stable, documented shape (the ``--json`` contract): top-level ``spec``,
    ``sequence``, ``conformant`` bool, ``counts`` tally, ``llm_summary``, and an
    ordered ``results`` list, each with ``key``/``status``/``expected``/
    ``actual``/``message``/``severity``/``fix_hint``. ``json.dumps`` never raises.
    """
    return {
        "spec": {"name": report.spec_name, "version": report.spec_version},
        "sequence": {"source": report.sequence_source},
        "conformant": report.conformant,
        "counts": report.counts(),
        "llm_summary": report.llm_summary,
        "results": [
            {
                "key": r.key,
                "status": str(r.status),
                "expected": r.expected,
                "actual": r.actual,
                "message": r.message,
                "severity": r.severity,
                "fix_hint": r.fix_hint,
            }
            for r in report.results
        ],
    }


def _verdict_line(report: SequenceReport) -> str:
    counts = report.counts()
    verdict = "CONFORMANT" if report.conformant else "NON-CONFORMANT"
    return (
        f"{verdict} — {counts['pass']} passed, {counts['fail']} failed, {counts['unknown']} unknown"
    )


def render_sequence_report(report: SequenceReport, *, color: bool = True) -> str:
    """Render a sequence report as a Rich-formatted string for terminal display.

    Returns the rendered text (so callers can print or capture it). ``color``
    toggles ANSI styling for non-TTY / CI logs. One row per rule, with the
    deterministic fix hint beneath each failure.
    """
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        force_terminal=color,
        no_color=not color,
        color_system="truecolor" if color else None,
        width=100,
        highlight=False,
    )

    title = f"{report.spec_name} v{report.spec_version}"
    console.print(f"[bold]{title}[/bold]" if color else title)
    console.print(f"Sequence: {report.sequence_source}")
    console.print(_verdict_line(report))

    table = Table(show_header=True, header_style="bold" if color else None)
    table.add_column("Rule")
    table.add_column("Status")
    table.add_column("Expected")
    table.add_column("Actual")
    table.add_column("Detail")

    for r in report.results:
        status_text = str(r.status).upper()
        if color:
            style = _STATUS_STYLES.get(str(r.status), "white")
            status_text = f"[{style}]{status_text}[/{style}]"
        table.add_row(
            r.key,
            status_text,
            str(r.expected),
            str(r.actual),
            r.message,
        )
    console.print(table)

    failures = report.failures
    if failures:
        console.print("\nFix hints:" if not color else "\n[bold]Fix hints:[/bold]")
        for r in failures:
            if r.fix_hint:
                console.print(f"  {r.key}:")
                console.print(f"    {r.fix_hint}")

    if report.llm_summary:
        console.print("\nSummary:" if not color else "\n[bold]Summary:[/bold]")
        console.print(report.llm_summary)

    return buffer.getvalue()


def render_sequence_report_markdown(report: SequenceReport) -> str:
    """Render a sequence report as portable Markdown for the ``--report`` flag.

    Includes a verdict/counts summary, a results table, and a fix hint per
    failure. Deterministic for a given report, so it is diffable in tests and
    stable as a CI artifact.
    """
    lines: list[str] = []
    lines.append(f"# Sequence conformance report: {report.spec_name} v{report.spec_version}")
    lines.append("")
    lines.append(f"- **Sequence:** `{report.sequence_source}`")
    verdict = "✅ CONFORMANT" if report.conformant else "❌ NON-CONFORMANT"
    lines.append(f"- **Verdict:** {verdict}")
    counts = report.counts()
    lines.append(
        f"- **Counts:** {counts['pass']} pass / {counts['fail']} fail / {counts['unknown']} unknown"
    )
    lines.append("")

    lines.append("## Results")
    lines.append("")
    lines.append("| Rule | Status | Expected | Actual | Detail |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in report.results:
        status = str(r.status).upper()
        detail = r.message.replace("|", "\\|")
        lines.append(f"| {r.key} | {status} | {r.expected} | {r.actual} | {detail} |")
    lines.append("")

    failures = report.failures
    if failures:
        lines.append("## Fix hints")
        lines.append("")
        for r in failures:
            lines.append(f"### `{r.key}`")
            lines.append("")
            lines.append(r.message)
            lines.append("")
            if r.fix_hint:
                lines.append(f"> {r.fix_hint}")
                lines.append("")

    if report.llm_summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(report.llm_summary)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
