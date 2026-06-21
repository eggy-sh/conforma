"""Render a :class:`ConformanceReport` for humans, machines, and Markdown.

Three projections of one report:

* :func:`report_to_dict` — the canonical JSON shape for the CLI's ``--json``
  output. A pure dict; round-trips losslessly through ``json.dumps``.
* :func:`render_report` — a Rich table/panel for terminal output (color-coded
  PASS/FAIL/UNKNOWN, fix commands under failures).
* :func:`render_report_markdown` — a portable Markdown report for the ``--report``
  flag (CI artifacts, PR comments), with a fenced ``ffmpeg`` block per failure.

Rendering is read-only: it never recomputes a verdict, so what you see is exactly
what :mod:`conforma.rules` decided.
"""

import io
from typing import Any

from rich.console import Console
from rich.table import Table

from .models import CheckStatus, ConformanceReport

#: Rich style per status (used by :func:`render_report`).
_STATUS_STYLES: dict[str, str] = {
    "pass": "green",
    "fail": "red",
    "unknown": "yellow",
}


def report_to_dict(report: ConformanceReport) -> dict[str, Any]:
    """Project a report into the canonical JSON-serializable dict.

    Stable, documented shape (the ``--json`` contract): top-level ``spec``,
    ``media``, ``conformant`` bool, ``counts`` tally, and an ordered ``results``
    list, each with ``key``/``status``/``expected``/``actual``/``message``/
    ``severity``/``fix_command``. ``json.dumps`` of this never raises.
    """
    return {
        "spec": {"name": report.spec_name, "version": report.spec_version},
        "media": {"source": report.media_source},
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
                "fix_command": r.fix_command,
            }
            for r in report.results
        ],
    }


def _verdict_line(report: ConformanceReport) -> str:
    counts = report.counts()
    verdict = "CONFORMANT" if report.conformant else "NON-CONFORMANT"
    return (
        f"{verdict} — {counts['pass']} passed, {counts['fail']} failed, {counts['unknown']} unknown"
    )


def render_report(report: ConformanceReport, *, color: bool = True) -> str:
    """Render a report as a Rich-formatted string for terminal display.

    Returns the rendered text (so callers can print or capture it). ``color``
    toggles ANSI styling for non-TTY / CI logs. Shows one row per requirement
    and the suggested ffmpeg fix beneath each failure.
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
    console.print(f"Media: {report.media_source}")
    console.print(_verdict_line(report))

    table = Table(show_header=True, header_style="bold" if color else None)
    table.add_column("Requirement")
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
        console.print("\nSuggested fixes:" if not color else "\n[bold]Suggested fixes:[/bold]")
        for r in failures:
            if r.fix_command:
                console.print(f"  {r.key}:")
                console.print(f"    {r.fix_command}")

    if report.llm_summary:
        console.print("\nSummary:" if not color else "\n[bold]Summary:[/bold]")
        console.print(report.llm_summary)

    return buffer.getvalue()


def render_report_markdown(report: ConformanceReport) -> str:
    """Render a report as portable Markdown for the ``--report`` flag.

    Includes a summary line (conformant?/counts), a results table, and a fenced
    ``ffmpeg`` code block per failure. Deterministic for a given report, so it is
    diffable in tests and stable as a CI artifact.
    """
    lines: list[str] = []
    lines.append(f"# Conformance report: {report.spec_name} v{report.spec_version}")
    lines.append("")
    lines.append(f"- **Media:** `{report.media_source}`")
    verdict = "✅ CONFORMANT" if report.conformant else "❌ NON-CONFORMANT"
    lines.append(f"- **Verdict:** {verdict}")
    counts = report.counts()
    lines.append(
        f"- **Counts:** {counts['pass']} pass / {counts['fail']} fail / {counts['unknown']} unknown"
    )
    lines.append("")

    lines.append("## Results")
    lines.append("")
    lines.append("| Requirement | Status | Expected | Actual | Detail |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in report.results:
        status = str(r.status).upper()
        detail = r.message.replace("|", "\\|")
        lines.append(f"| {r.key} | {status} | {r.expected} | {r.actual} | {detail} |")
    lines.append("")

    failures = report.failures
    if failures:
        lines.append("## Suggested fixes")
        lines.append("")
        for r in failures:
            lines.append(f"### `{r.key}`")
            lines.append("")
            lines.append(r.message)
            lines.append("")
            if r.fix_command:
                lines.append("```ffmpeg")
                lines.append(r.fix_command)
                lines.append("```")
                lines.append("")

    if report.llm_summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(report.llm_summary)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# CheckStatus is imported for completeness so callers can build their own
# projections from the same status vocabulary.
__all__ = [
    "report_to_dict",
    "render_report",
    "render_report_markdown",
    "CheckStatus",
]
