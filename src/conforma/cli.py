"""The conforma CLI: a Typer + Rich shell over the deterministic engine.

Like replykit's CLI, every command is automation-friendly: ``--json`` prints
**exactly one** JSON object to stdout and nothing else, so conforma drops cleanly
into CI and agent pipelines. The CLI never requires ffmpeg/ffprobe — it auto-probes
only when a non-JSON media path is given *and* ffprobe is on PATH, otherwise it
asks for probe JSON.

Owned by SWE-CLI. It imports only conforma's public API (``conforma`` package
root); it must not reach into private module internals.

Exit codes (a stable contract for CI):

* ``0`` — the media is conformant with the spec.
* ``1`` — the media is **not** conformant (a blocking requirement failed).
* ``2`` — a usage / IO error (bad spec, unreadable probe JSON, no ffprobe for a
  non-JSON media path, etc.).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import typer
from rich.console import Console

import conforma

app = typer.Typer(
    name="conforma",
    help="Delivery-spec compliance checks for post-production media.",
    no_args_is_help=True,
    add_completion=False,
)

#: stdout console — human output and the single ``--json`` object both go here.
console = Console()
#: stderr console — human-facing error messages never pollute stdout.
err_console = Console(stderr=True)

#: Exit code conventions, named so call sites read clearly.
EXIT_OK = 0
EXIT_NONCONFORMANT = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# Shared output helpers — keep the automation contract in one place.
# ---------------------------------------------------------------------------


def _emit_json(payload: dict[str, Any]) -> None:
    """Print exactly one JSON object to stdout and nothing else.

    Uses ``json.dumps`` (not Rich's pretty printer) so the bytes on stdout are a
    single, parser-friendly object with no ANSI escapes — the automation
    contract every ``--json`` command honors.
    """
    sys.stdout.write(json.dumps(payload) + "\n")


def _fail(message: str, *, as_json: bool) -> None:
    """Report a usage/IO error and raise ``typer.Exit(2)``.

    With ``--json`` the single stdout object is ``{"error": message}`` (still the
    automation contract); otherwise the message goes to stderr so stdout stays
    clean for pipelines. Never returns — always raises ``typer.Exit``.
    """
    if as_json:
        _emit_json({"error": message})
    else:
        err_console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(EXIT_USAGE)


# ---------------------------------------------------------------------------
# Resolvers — turn user-supplied strings into validated domain objects. These
# raise ``conforma.ConformaError`` on bad input, which the commands translate
# into a clean exit code 2.
# ---------------------------------------------------------------------------


def _resolve_spec(spec: str) -> conforma.Spec:
    """Resolve a ``--spec`` value into a validated :class:`conforma.Spec`.

    A bare preset name (``netflix-hd``, ``ebu-broadcast``) loads the shipped
    preset; anything that looks like a path loads and validates that YAML file.
    Preset names take precedence so ``--spec netflix-hd`` works without a file.
    Raises :class:`conforma.SpecError` on an unknown preset / bad file.
    """
    if spec in conforma.PRESETS:
        return conforma.load_preset(spec)
    # Not a known preset: it must be a spec file on disk.
    if os.path.isfile(spec):
        return conforma.load_spec(spec)
    raise conforma.SpecError(
        f"unknown spec {spec!r}: not a shipped preset "
        f"({', '.join(conforma.list_presets())}) and not a readable file"
    )


def _looks_like_json(path: str) -> bool:
    """Heuristic: does this path point at probe JSON rather than a media file?

    A ``.json`` suffix is treated as probe JSON unconditionally. This keeps the
    auto-probe decision predictable and lets the hermetic test suite drive the
    CLI entirely off committed ``*.json`` fixtures.
    """
    return path.lower().endswith(".json")


def _resolve_profile(media: str) -> conforma.MediaProfile:
    """Resolve a media argument into a normalized :class:`conforma.MediaProfile`.

    * A ``*.json`` path is loaded as probe JSON (ffprobe **or** MediaInfo).
    * Any other path is auto-probed with ``ffprobe`` **only when it is on PATH**
      (:func:`conforma.ffprobe_available`); otherwise this is a usage error and
      the caller is told to pass probe JSON instead.

    Raises :class:`conforma.ProbeError` (or :class:`conforma.SpecError` shape) on
    bad input so commands can map it to exit code 2.
    """
    if _looks_like_json(media):
        return conforma.load_probe(media)
    if conforma.ffprobe_available():
        return conforma.probe_media(media)
    raise conforma.ProbeError(
        f"cannot probe {media!r}: ffprobe is not on PATH. Pass a probe JSON file "
        "(ffprobe -print_format json, or MediaInfo --Output=JSON) instead."
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def check(
    media: str = typer.Argument(
        ...,
        help="Path to a probe JSON file (ffprobe/MediaInfo) or a media file "
        "(auto-probed if ffprobe is on PATH).",
    ),
    spec: str = typer.Option(
        ...,
        "--spec",
        "-s",
        help="Preset name (e.g. 'netflix-hd', 'ebu-broadcast') or path to a spec YAML.",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Print exactly one JSON object to stdout and nothing else."
    ),
    report: str | None = typer.Option(
        None, "--report", help="Write a Markdown conformance report to this path."
    ),
) -> None:
    """Check a media file's probe against a delivery spec and report conformance.

    Resolves the spec (preset name or YAML path), loads/normalizes the probe
    (from JSON, or by auto-probing a media file when ffprobe is available), runs
    the deterministic pre-checks plus fix suggestions, and renders the report.
    Exit code is ``0`` when conformant, ``1`` when not, ``2`` on a usage/IO error.
    """
    try:
        resolved_spec = _resolve_spec(spec)
        profile = _resolve_profile(media)
    except conforma.ConformaError as exc:
        _fail(str(exc), as_json=json_out)
        return  # unreachable: _fail raises

    # No model -> the hermetic, deterministic report (verdicts never come from an
    # LLM). input_path is the media argument so generated ffmpeg commands are copy-
    # pasteable starting points.
    agent = conforma.ConformanceAgent()
    conformance = agent.check(resolved_spec, profile, input_path=media)

    if report is not None:
        try:
            markdown = conforma.render_report_markdown(conformance)
            with open(report, "w", encoding="utf-8") as fh:
                fh.write(markdown)
        except OSError as exc:
            _fail(f"could not write report to {report!r}: {exc}", as_json=json_out)
            return

    if json_out:
        _emit_json(conforma.report_to_dict(conformance))
    else:
        console.print(conforma.render_report(conformance))

    raise typer.Exit(EXIT_OK if conformance.conformant else EXIT_NONCONFORMANT)


@app.command()
def presets(
    json_out: bool = typer.Option(False, "--json", help="Emit the preset list as JSON."),
) -> None:
    """List the delivery-spec presets conforma ships."""
    names = conforma.list_presets()

    if json_out:
        items = []
        for name in names:
            spec = conforma.load_preset(name)
            items.append(
                {
                    "name": name,
                    "spec_name": spec.name,
                    "version": spec.version,
                    "description": spec.description,
                    "requirements": len(spec.requirements),
                }
            )
        _emit_json({"presets": items})
        return

    from rich.table import Table

    table = Table(title="conforma presets")
    table.add_column("name", style="cyan", no_wrap=True)
    table.add_column("spec")
    table.add_column("version", justify="right")
    table.add_column("requirements", justify="right")
    for name in names:
        spec = conforma.load_preset(name)
        table.add_row(name, spec.name, spec.version, str(len(spec.requirements)))
    console.print(table)


@app.command()
def show(
    spec: str = typer.Argument(..., help="Preset name or spec YAML path to display."),
    json_out: bool = typer.Option(False, "--json", help="Emit the parsed spec as JSON."),
) -> None:
    """Parse a spec (preset or file) and print its validated requirements."""
    try:
        resolved = _resolve_spec(spec)
    except conforma.ConformaError as exc:
        _fail(str(exc), as_json=json_out)
        return  # unreachable: _fail raises

    if json_out:
        _emit_json(resolved.as_dict())
        return

    from rich.table import Table

    console.print(
        f"[bold]{resolved.name}[/bold] [dim]v{resolved.version}[/dim]"
        + (f" — {resolved.source}" if resolved.source else "")
    )
    if resolved.description:
        console.print(resolved.description.strip())
    table = Table(title="requirements")
    table.add_column("key", style="cyan", no_wrap=True)
    table.add_column("expected")
    table.add_column("tolerance", justify="right")
    table.add_column("severity")
    table.add_column("description")
    for req in resolved.requirements:
        table.add_row(
            req.key,
            json.dumps(req.expected),
            "" if req.tolerance is None else str(req.tolerance),
            req.severity,
            req.description,
        )
    console.print(table)


def main() -> None:
    """Console-script entry point (``conforma`` -> ``conforma.cli:main``)."""
    app()


if __name__ == "__main__":
    main()
