#!/usr/bin/env python3
"""Check an exported timeline against the ``netflix-imf`` sequence preset.

Fully hermetic: loads the two committed example timelines
(``examples/seq_netflix_pass.otio`` and ``examples/seq_netflix_fail.otio``,
lossless OpenTimelineIO), resolves the shipped Netflix-style IMF sequence preset,
runs conforma's **deterministic** sequence checks (slate present + ~5 s, reference
audio muted, track counts) with **no LLM, no NLE, no network**, and prints each
verdict plus a per-rule table and machine-readable JSON. It also demonstrates the
deterministic ``--fix`` corrector on the failing timeline.

Run it::

    python examples/check_sequence.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import conforma

HERE = Path(__file__).resolve().parent


def _check(seq_path: Path, spec: conforma.DeliverySpec) -> conforma.SequenceReport:
    timeline = conforma.read_timeline(str(seq_path))
    layout = conforma.extract_layout(timeline, source=seq_path.name)
    # No model -> a purely deterministic report. The agent layer would only add a
    # narrative or fill ambiguous roles; the verdict itself never comes from an LLM.
    return conforma.SequenceConformanceAgent().check(spec, layout)


def main() -> None:
    spec = conforma.load_seq_preset("netflix-imf")

    for name in ("seq_netflix_pass.otio", "seq_netflix_fail.otio"):
        seq_path = HERE / name
        report = _check(seq_path, spec)

        print(f"Spec:     {spec.name} v{spec.version}")
        print(f"Sequence: {report.sequence_source}")
        print(f"Verdict:  {'CONFORMANT' if report.conformant else 'NON-CONFORMANT'}")
        print(f"Counts:   {report.counts()}")
        print()
        print(conforma.render_sequence_report(report, color=False))
        print("--- JSON (the --json contract) ---")
        print(json.dumps(conforma.sequence_report_to_dict(report), indent=2))
        print("=" * 72)

    # Deterministic corrector: mute the reference track + flag the slate, written
    # back as a corrected timeline. Never mutates the source.
    fail_path = HERE / "seq_netflix_fail.otio"
    timeline = conforma.read_timeline(str(fail_path))
    layout = conforma.extract_layout(timeline, source=fail_path.name)
    report = conforma.SequenceConformanceAgent().check(spec, layout)
    out = Path(tempfile.mkdtemp()) / "seq_netflix_fixed.otio"
    conforma.fix_sequence(timeline, layout, report, str(out))
    print(f"Wrote corrected timeline -> {out}")


if __name__ == "__main__":
    main()
