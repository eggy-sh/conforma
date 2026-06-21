#!/usr/bin/env python3
"""Check a probe against the shipped ``netflix-hd`` preset — fully hermetic.

Loads the committed ``examples/probe_netflix_pass.json`` (real ffprobe-shaped
JSON for a 1080p ProRes 422 HQ / 23.976p / 10-bit / 48 kHz PCM master), resolves
the built-in Netflix-style preset, runs conforma's **deterministic** pre-checks
(no LLM, no ffmpeg, no network), and prints the verdict plus a per-requirement
table and machine-readable JSON.

Run it::

    python examples/check_netflix.py
"""

from __future__ import annotations

import json
from pathlib import Path

import conforma

HERE = Path(__file__).resolve().parent


def main() -> None:
    spec = conforma.load_preset("netflix-hd")
    profile = conforma.load_probe(str(HERE / "probe_netflix_pass.json"))

    # No model -> a purely deterministic report. The agent layer would only add a
    # narrative; the verdict itself never comes from an LLM.
    report = conforma.ConformanceAgent().check(spec, profile, input_path="netflix_master.mov")

    print(f"Spec:   {spec.name} v{spec.version}")
    print(f"Media:  {report.media_source}")
    print(f"Verdict: {'CONFORMANT' if report.conformant else 'NON-CONFORMANT'}")
    print(f"Counts:  {report.counts()}")
    print()

    # The human-facing rendering (Rich-formatted string).
    print(conforma.render_report(report, color=False))

    # The machine-readable projection — the same shape the CLI's --json emits.
    print("\n--- JSON (the --json contract) ---")
    print(json.dumps(conforma.report_to_dict(report), indent=2))


if __name__ == "__main__":
    main()
