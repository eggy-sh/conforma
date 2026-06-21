#!/usr/bin/env python3
"""Check a non-conforming master against the ``ebu-broadcast`` preset.

This example shows the *failure* path: an in-memory ffprobe-shaped payload for a
web proxy (H.264 / 720p / 29.97p / AAC in an MP4) is checked against the EBU
broadcast HD preset (MXF / 1080i25 / MPEG-2 / PCM). Several requirements FAIL,
and each FAIL carries a concrete ``ffmpeg`` fix command an operator can review.

Everything is hermetic: the probe payload is built inline (no ffprobe), the spec
is a shipped preset, and there is no LLM call — verdicts are deterministic.

Run it::

    python examples/check_ebu.py
"""

from __future__ import annotations

import json

import conforma

# An inline ffprobe-shaped payload (what `ffprobe -print_format json` emits for a
# typical web proxy that is *not* a broadcast master).
WEB_PROXY_PROBE = {
    "streams": [
        {
            "index": 0,
            "codec_name": "h264",
            "codec_type": "video",
            "width": 1280,
            "height": 720,
            "pix_fmt": "yuv420p",
            "field_order": "progressive",
            "r_frame_rate": "30000/1001",
            "bits_per_raw_sample": "8",
        },
        {
            "index": 1,
            "codec_name": "aac",
            "codec_type": "audio",
            "sample_rate": "44100",
            "channels": 2,
        },
    ],
    "format": {
        "filename": "web_proxy.mp4",
        "nb_streams": 2,
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "duration": "120.500000",
    },
}


def main() -> None:
    spec = conforma.load_preset("ebu-broadcast")
    profile = conforma.normalize_probe(WEB_PROXY_PROBE, source="web_proxy.mp4")

    report = conforma.ConformanceAgent().check(spec, profile, input_path="web_proxy.mp4")

    print(f"Spec:    {spec.name} v{spec.version}")
    print(f"Media:   {report.media_source}")
    print(f"Verdict: {'CONFORMANT' if report.conformant else 'NON-CONFORMANT'}")
    print(f"Counts:  {report.counts()}")
    print()

    print("Failures and suggested ffmpeg fixes:")
    for result in report.failures:
        print(f"  - {result.key}: expected {result.expected!r}, got {result.actual!r}")
        if result.fix_command:
            print(f"      fix: {result.fix_command}")

    print("\n--- Markdown report (the --report artifact) ---")
    print(conforma.render_report_markdown(report))

    print("\n--- JSON (the --json contract) ---")
    print(json.dumps(conforma.report_to_dict(report), indent=2))


if __name__ == "__main__":
    main()
