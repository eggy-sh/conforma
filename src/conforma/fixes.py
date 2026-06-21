"""Suggest a concrete ``ffmpeg`` fix command for a failing requirement.

Each deterministic FAIL gets an actionable remediation: the exact ``ffmpeg``
invocation that would re-encode/re-wrap the input toward conformance.
:func:`suggest_fix` is pure and deterministic — same failure in, same command
out — so the suggestion is testable from fixtures without ever running ffmpeg.

The commands are intentionally conservative (re-encode the offending dimension,
copy the rest where safe) and are meant as a starting point an operator reviews,
not a blind auto-run. The agent layer reuses this function as its fix tool, so
the LLM cannot invent an unverified command: it can only surface what
:func:`suggest_fix` produced.
"""

import os

from .models import CheckStatus, RuleResult

#: Placeholder tokens used in generated commands when real paths are unknown.
INPUT_PLACEHOLDER = "INPUT"
OUTPUT_PLACEHOLDER = "OUTPUT"

#: Spec codec name -> the ffmpeg *encoder* that produces it.
_VIDEO_ENCODERS: dict[str, str] = {
    "prores": "prores_ks",
    "prores_ks": "prores_ks",
    "mpeg2video": "mpeg2video",
    "xdcam": "mpeg2video",
    "h264": "libx264",
    "h265": "libx265",
    "hevc": "libx265",
    "dnxhd": "dnxhd",
}

#: Spec audio codec name -> the ffmpeg encoder for it.
_AUDIO_ENCODERS: dict[str, str] = {
    "pcm": "pcm_s24le",
    "pcm_s16le": "pcm_s16le",
    "pcm_s24le": "pcm_s24le",
    "aac": "aac",
}

#: Required video bit depth -> a representative 4:2:2 pixel format.
_PIX_FMT_FOR_DEPTH: dict[int, str] = {
    8: "yuv422p",
    10: "yuv422p10le",
    12: "yuv422p12le",
}

#: Container name -> output file extension.
_CONTAINER_EXT: dict[str, str] = {
    "mov": "mov",
    "mp4": "mp4",
    "mxf": "mxf",
    "mkv": "mkv",
    "mka": "mka",
}


def _first_expected(expected: object) -> object:
    if isinstance(expected, (list, tuple)):
        return expected[0] if expected else None
    return expected


def _retarget_output(output_path: str, ext: str) -> str:
    """Return ``output_path`` with its extension swapped to ``ext``."""
    root, _ = os.path.splitext(output_path)
    return f"{root}.{ext}"


def _ffmpeg(input_path: str, middle: str, output_path: str) -> str:
    return f"ffmpeg -i {input_path} {middle} {output_path}".strip()


def suggest_fix(
    result: RuleResult,
    *,
    input_path: str = INPUT_PLACEHOLDER,
    output_path: str = OUTPUT_PLACEHOLDER,
) -> str:
    """Return an ``ffmpeg`` command that remediates a single failing requirement.

    Dispatches on ``result.key`` to build a targeted command (scale filter for
    resolution, ``-r`` for frame rate, ``-c:v``/``-pix_fmt`` for codec/bit depth,
    ``-c:a``/``-ac``/``-ar`` for audio, container change via the output
    extension, etc.). For a PASS/UNKNOWN result, or a key with no known
    remediation, returns an empty string. ``input_path`` / ``output_path`` are
    substituted into the command; defaults are placeholders so the function is
    pure for fixture tests.
    """
    if result.status != CheckStatus.FAIL:
        return ""

    key = result.key
    expected = result.expected

    if key == "resolution":
        exp = expected if isinstance(expected, (list, tuple)) else None
        if not exp or len(exp) < 2:
            return ""
        width, height = exp[0], exp[1]
        return _ffmpeg(input_path, f"-vf scale={width}:{height} -c:a copy", output_path)

    if key == "frame_rate":
        target = _first_expected(expected)
        if target is None:
            return ""
        return _ffmpeg(input_path, f"-r {target:g} -c:a copy", output_path)

    if key == "video_codec":
        target = _first_expected(expected)
        encoder = _VIDEO_ENCODERS.get(str(target).lower(), str(target))
        return _ffmpeg(input_path, f"-c:v {encoder} -c:a copy", output_path)

    if key == "bit_depth":
        target = _first_expected(expected)
        depth = int(target) if isinstance(target, (int, float)) else None
        pix_fmt = _PIX_FMT_FOR_DEPTH.get(depth, "yuv422p10le") if depth else "yuv422p10le"
        return _ffmpeg(input_path, f"-pix_fmt {pix_fmt} -c:a copy", output_path)

    if key == "scan_type":
        target = str(_first_expected(expected) or "").lower()
        if target == "progressive":
            return _ffmpeg(input_path, "-vf yadif=mode=1 -c:a copy", output_path)
        return _ffmpeg(input_path, "-flags +ilme+ildct -c:a copy", output_path)

    if key == "audio_codec":
        target = _first_expected(expected)
        encoder = _AUDIO_ENCODERS.get(str(target).lower(), str(target))
        return _ffmpeg(input_path, f"-c:a {encoder} -c:v copy", output_path)

    if key == "audio_channels":
        target = _first_expected(expected)
        return _ffmpeg(input_path, f"-ac {int(target)} -c:v copy", output_path)

    if key == "audio_sample_rate":
        target = _first_expected(expected)
        return _ffmpeg(input_path, f"-ar {int(target)} -c:v copy", output_path)

    if key == "container":
        target = str(_first_expected(expected) or "").lower()
        ext = _CONTAINER_EXT.get(target, target or "mov")
        retargeted = _retarget_output(output_path, ext)
        return _ffmpeg(input_path, "-c copy", retargeted)

    return ""
