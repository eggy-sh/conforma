"""Deterministic rule pre-checks: the heart of conforma.

A :class:`Rule` evaluates exactly one requirement ``key`` against a normalized
:class:`~conforma.models.MediaProfile` and returns a
:class:`~conforma.models.RuleResult` — with **no LLM involvement**. The full
pass/fail verdict is computed here; the :mod:`conforma.agent` layer only narrates
and attaches fixes. This keeps conformance verdicts reproducible and testable
from committed fixtures.

The shipped rules cover the delivery-spec essentials: resolution, frame rate
(with tolerance), video codec, bit depth, audio codec, audio channel count,
audio sample rate, scan type, and container. :data:`RULES` is the registry the
spec validator checks requirement keys against.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import AudioProfile, CheckStatus, MediaProfile, Requirement, RuleResult

#: A small default tolerance for frame-rate comparison, so a rational rate like
#: ``24000/1001`` (≈23.976) matches a spec value of ``23.976`` even though they
#: differ in the fourth decimal place.
DEFAULT_FRAME_RATE_TOLERANCE = 0.05


@dataclass(frozen=True)
class Rule:
    """One named, deterministic check.

    ``key`` is the requirement key it handles (the link from a spec line to a
    rule). ``check`` is a pure function ``(Requirement, MediaProfile) ->
    RuleResult``; it must never raise on a well-formed profile, returning
    :attr:`~conforma.models.CheckStatus.UNKNOWN` when the probe lacks the needed
    field. ``label`` is the human-facing name for the report.
    """

    key: str
    label: str
    check: Callable[[Requirement, MediaProfile], RuleResult]


# --- Matching helpers ------------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    """Coerce a scalar-or-list ``expected`` value into a list."""
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _codec_matches(expected: str, actual: str) -> bool:
    """Case-insensitive, alias-aware codec/container match.

    ``expected`` (from the spec) matches ``actual`` (from the probe) when, after
    lowercasing: they are equal; ``actual`` is one of ``expected``'s aliases;
    ``expected`` is one of ``actual``'s aliases; or one is a prefix-family of the
    other (e.g. spec ``prores`` vs probe ``prores_ks``).
    """
    e = expected.strip().lower()
    a = actual.strip().lower()
    if not e or not a:
        return False
    if e == a:
        return True
    if a in CODEC_ALIASES.get(e, set()):
        return True
    if e in CODEC_ALIASES.get(a, set()):
        return True
    # Prefix family: "prores" matches "prores_ks"; "pcm" matches "pcm_s24le".
    if a.startswith(e + "_") or e.startswith(a + "_"):
        return True
    return False


def _any_codec_matches(expecteds: list[Any], actual: str) -> bool:
    return any(_codec_matches(str(e), actual) for e in expecteds)


# --- Individual rule implementations ---------------------------------------
#
# Each takes (requirement, profile) and returns a RuleResult. They are pure and
# total: a missing probe field yields CheckStatus.UNKNOWN, never an exception.


def check_resolution(req: Requirement, profile: MediaProfile) -> RuleResult:
    """Check video width x height against ``expected`` ``[width, height]``.

    ``expected`` is a two-element ``[width, height]`` list. UNKNOWN if the probe
    reported no video dimensions.
    """
    video = profile.video
    width = video.width if video else None
    height = video.height if video else None
    expected = list(req.expected) if isinstance(req.expected, (list, tuple)) else req.expected
    actual = [width, height]
    if width is None or height is None:
        return RuleResult(
            key=req.key,
            status=CheckStatus.UNKNOWN,
            expected=expected,
            actual=actual,
            message="No video resolution reported by the probe.",
            severity=req.severity,
        )
    exp_w, exp_h = expected[0], expected[1]
    status = CheckStatus.PASS if (width == exp_w and height == exp_h) else CheckStatus.FAIL
    if status == CheckStatus.PASS:
        message = f"Resolution {width}x{height} matches {exp_w}x{exp_h}."
    else:
        message = f"Resolution {width}x{height} does not match required {exp_w}x{exp_h}."
    return RuleResult(
        key=req.key,
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        severity=req.severity,
    )


def check_frame_rate(req: Requirement, profile: MediaProfile) -> RuleResult:
    """Check video frame rate against ``expected`` fps within ``tolerance``.

    ``expected`` is a float (e.g. ``23.976``); ``tolerance`` (a small default
    when ``None``) absorbs rational-rate rounding. ``expected`` may also be a
    list of accepted rates. UNKNOWN if the probe reported no frame rate.
    """
    video = profile.video
    actual = video.frame_rate if video else None
    expected = req.expected
    if actual is None:
        return RuleResult(
            key=req.key,
            status=CheckStatus.UNKNOWN,
            expected=expected,
            actual=actual,
            message="No frame rate reported by the probe.",
            severity=req.severity,
        )
    tol = req.tolerance if req.tolerance is not None else DEFAULT_FRAME_RATE_TOLERANCE
    candidates = [float(e) for e in _as_list(expected)]
    matched = any(abs(actual - target) <= tol for target in candidates)
    status = CheckStatus.PASS if matched else CheckStatus.FAIL
    shown = "/".join(f"{c:g}" for c in candidates)
    if status == CheckStatus.PASS:
        message = f"Frame rate {actual:.3f} fps within {tol:g} of {shown}."
    else:
        message = f"Frame rate {actual:.3f} fps not within {tol:g} of {shown}."
    return RuleResult(
        key=req.key,
        status=status,
        expected=expected,
        actual=round(actual, 3),
        message=message,
        severity=req.severity,
    )


def check_video_codec(req: Requirement, profile: MediaProfile) -> RuleResult:
    """Check the video codec against ``expected`` (a name or list of names).

    Comparison is case-insensitive and alias-aware (e.g. ``"prores"`` matches
    ffprobe's ``"prores_ks"`` family per :data:`CODEC_ALIASES`). UNKNOWN if no
    video codec was reported.
    """
    video = profile.video
    actual = video.codec if video else None
    expected = req.expected
    if not actual:
        return RuleResult(
            key=req.key,
            status=CheckStatus.UNKNOWN,
            expected=expected,
            actual=actual,
            message="No video codec reported by the probe.",
            severity=req.severity,
        )
    matched = _any_codec_matches(_as_list(expected), actual)
    status = CheckStatus.PASS if matched else CheckStatus.FAIL
    shown = "/".join(str(e) for e in _as_list(expected))
    if status == CheckStatus.PASS:
        message = f"Video codec {actual!r} matches {shown}."
    else:
        message = f"Video codec {actual!r} does not match required {shown}."
    return RuleResult(
        key=req.key,
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        severity=req.severity,
    )


def check_bit_depth(req: Requirement, profile: MediaProfile) -> RuleResult:
    """Check video bit depth against ``expected`` (an int or list of ints).

    UNKNOWN if no bit depth was reported.
    """
    video = profile.video
    actual = video.bit_depth if video else None
    expected = req.expected
    if actual is None:
        return RuleResult(
            key=req.key,
            status=CheckStatus.UNKNOWN,
            expected=expected,
            actual=actual,
            message="No video bit depth reported by the probe.",
            severity=req.severity,
        )
    candidates = [int(e) for e in _as_list(expected)]
    status = CheckStatus.PASS if actual in candidates else CheckStatus.FAIL
    shown = "/".join(str(c) for c in candidates)
    if status == CheckStatus.PASS:
        message = f"Bit depth {actual}-bit matches {shown}-bit."
    else:
        message = f"Bit depth {actual}-bit does not match required {shown}-bit."
    return RuleResult(
        key=req.key,
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        severity=req.severity,
    )


def check_scan_type(req: Requirement, profile: MediaProfile) -> RuleResult:
    """Check progressive/interlaced scan against ``expected``.

    ``expected`` is ``"progressive"`` or ``"interlaced"`` (case-insensitive).
    UNKNOWN if scan type was not reported.
    """
    video = profile.video
    actual = video.scan_type if video else None
    expected = req.expected
    if not actual:
        return RuleResult(
            key=req.key,
            status=CheckStatus.UNKNOWN,
            expected=expected,
            actual=actual,
            message="No scan type reported by the probe.",
            severity=req.severity,
        )
    candidates = [str(e).strip().lower() for e in _as_list(expected)]
    status = CheckStatus.PASS if actual.strip().lower() in candidates else CheckStatus.FAIL
    shown = "/".join(candidates)
    if status == CheckStatus.PASS:
        message = f"Scan type {actual!r} matches {shown}."
    else:
        message = f"Scan type {actual!r} does not match required {shown}."
    return RuleResult(
        key=req.key,
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        severity=req.severity,
    )


def _audio_attr(audio: list[AudioProfile], attr: str) -> list[Any]:
    """Collect a non-None attribute across all audio streams."""
    return [getattr(a, attr) for a in audio if getattr(a, attr) is not None]


def check_audio_codec(req: Requirement, profile: MediaProfile) -> RuleResult:
    """Check that *some* audio stream matches ``expected`` codec(s).

    Passes if any audio stream's codec matches; FAILs only when audio exists but
    none match. UNKNOWN if the file reports no audio streams.
    """
    expected = req.expected
    codecs = _audio_attr(profile.audio, "codec")
    if not codecs:
        return RuleResult(
            key=req.key,
            status=CheckStatus.UNKNOWN,
            expected=expected,
            actual=None,
            message="No audio codec reported by the probe.",
            severity=req.severity,
        )
    expecteds = _as_list(expected)
    matched = any(_any_codec_matches(expecteds, c) for c in codecs)
    status = CheckStatus.PASS if matched else CheckStatus.FAIL
    shown = "/".join(str(e) for e in expecteds)
    actual = codecs[0] if len(codecs) == 1 else codecs
    if status == CheckStatus.PASS:
        message = f"Audio codec {actual!r} matches {shown}."
    else:
        message = f"No audio stream matches required codec {shown} (found {codecs})."
    return RuleResult(
        key=req.key,
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        severity=req.severity,
    )


def check_audio_channels(req: Requirement, profile: MediaProfile) -> RuleResult:
    """Check that some audio stream has ``expected`` channel count.

    ``expected`` is an int (e.g. ``2`` for stereo, ``6`` for 5.1) or a list.
    UNKNOWN if no audio streams report a channel count.
    """
    expected = req.expected
    channels = _audio_attr(profile.audio, "channels")
    if not channels:
        return RuleResult(
            key=req.key,
            status=CheckStatus.UNKNOWN,
            expected=expected,
            actual=None,
            message="No audio channel count reported by the probe.",
            severity=req.severity,
        )
    candidates = [int(e) for e in _as_list(expected)]
    matched = any(c in candidates for c in channels)
    status = CheckStatus.PASS if matched else CheckStatus.FAIL
    shown = "/".join(str(c) for c in candidates)
    actual = channels[0] if len(channels) == 1 else channels
    if status == CheckStatus.PASS:
        message = f"Audio channels {actual} matches {shown}."
    else:
        message = f"No audio stream has required channel count {shown} (found {channels})."
    return RuleResult(
        key=req.key,
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        severity=req.severity,
    )


def check_audio_sample_rate(req: Requirement, profile: MediaProfile) -> RuleResult:
    """Check that some audio stream has ``expected`` sample rate (Hz).

    ``expected`` is an int (e.g. ``48000``) or a list. UNKNOWN if no audio stream
    reports a sample rate.
    """
    expected = req.expected
    rates = _audio_attr(profile.audio, "sample_rate")
    if not rates:
        return RuleResult(
            key=req.key,
            status=CheckStatus.UNKNOWN,
            expected=expected,
            actual=None,
            message="No audio sample rate reported by the probe.",
            severity=req.severity,
        )
    candidates = [int(e) for e in _as_list(expected)]
    matched = any(r in candidates for r in rates)
    status = CheckStatus.PASS if matched else CheckStatus.FAIL
    shown = "/".join(str(c) for c in candidates)
    actual = rates[0] if len(rates) == 1 else rates
    if status == CheckStatus.PASS:
        message = f"Audio sample rate {actual} Hz matches {shown} Hz."
    else:
        message = f"No audio stream has required sample rate {shown} Hz (found {rates})."
    return RuleResult(
        key=req.key,
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        severity=req.severity,
    )


def check_container(req: Requirement, profile: MediaProfile) -> RuleResult:
    """Check the container/wrapper against ``expected`` (a name or list).

    Comparison is case-insensitive and alias-aware (ffprobe reports comma-joined
    ``format_name`` like ``"mov,mp4,m4a,..."``; a spec value of ``"mov"`` matches
    if present). UNKNOWN if no container was reported.
    """
    actual = profile.container
    expected = req.expected
    if not actual:
        return RuleResult(
            key=req.key,
            status=CheckStatus.UNKNOWN,
            expected=expected,
            actual=actual,
            message="No container/format reported by the probe.",
            severity=req.severity,
        )
    # ffprobe's format_name may be a comma-joined family list.
    parts = [p.strip() for p in actual.split(",") if p.strip()]
    expecteds = _as_list(expected)
    matched = any(_codec_matches(str(e), part) for e in expecteds for part in parts)
    status = CheckStatus.PASS if matched else CheckStatus.FAIL
    shown = "/".join(str(e) for e in expecteds)
    if status == CheckStatus.PASS:
        message = f"Container {actual!r} matches {shown}."
    else:
        message = f"Container {actual!r} does not match required {shown}."
    return RuleResult(
        key=req.key,
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        severity=req.severity,
    )


#: Codec name -> set of equivalent probe-reported names, for tolerant matching.
#: Consulted by the codec/container rules. Lowercase keys and values throughout.
CODEC_ALIASES: dict[str, set[str]] = {
    # Video
    "prores": {
        "prores",
        "prores_ks",
        "prores_aw",
        "apch",
        "apcn",
        "apcs",
        "apco",
        "ap4h",
        "ap4x",
    },
    "mpeg2video": {"mpeg2video", "mpeg2", "xdcam", "mpeg-2 video", "hdcam"},
    "xdcam": {"xdcam", "mpeg2video", "mpeg2"},
    "h264": {"h264", "avc", "avc1", "x264"},
    "h265": {"h265", "hevc", "hvc1", "x265"},
    "hevc": {"hevc", "h265", "hvc1"},
    "dnxhd": {"dnxhd", "dnxhr", "avdn"},
    # Audio
    "pcm": {
        "pcm",
        "pcm_s16le",
        "pcm_s16be",
        "pcm_s24le",
        "pcm_s24be",
        "pcm_s32le",
        "pcm_s32be",
        "pcm_f32le",
        "in24",
        "in32",
        "lpcm",
        "twos",
        "sowt",
    },
    "aac": {"aac", "mp4a", "aac_lc", "aac-lc"},
    # Containers
    "mov": {"mov", "qt", "quicktime", "mp4"},
    "mxf": {"mxf", "mxf_op1a", "material exchange format"},
    "mp4": {"mp4", "mov", "m4v", "mpeg-4"},
}

#: The rule registry: requirement key -> :class:`Rule`. The spec validator checks
#: every requirement ``key`` is present here; the report iterates it in spec
#: order. Built from the rule functions above.
RULES: dict[str, Rule] = {
    "resolution": Rule("resolution", "Resolution", check_resolution),
    "frame_rate": Rule("frame_rate", "Frame rate", check_frame_rate),
    "video_codec": Rule("video_codec", "Video codec", check_video_codec),
    "bit_depth": Rule("bit_depth", "Bit depth", check_bit_depth),
    "scan_type": Rule("scan_type", "Scan type", check_scan_type),
    "audio_codec": Rule("audio_codec", "Audio codec", check_audio_codec),
    "audio_channels": Rule("audio_channels", "Audio channels", check_audio_channels),
    "audio_sample_rate": Rule("audio_sample_rate", "Audio sample rate", check_audio_sample_rate),
    "container": Rule("container", "Container", check_container),
}


def check_requirement(req: Requirement, profile: MediaProfile) -> RuleResult:
    """Evaluate a single requirement, dispatching to its rule via :data:`RULES`.

    Raises :class:`KeyError` only if ``req.key`` is unknown — which the spec
    validator already prevents, so in practice this never raises for a validated
    spec.
    """
    rule = RULES[req.key]
    return rule.check(req, profile)


def check_all(spec_requirements: list[Requirement], profile: MediaProfile) -> list[RuleResult]:
    """Evaluate every requirement against ``profile``, preserving spec order.

    This is the deterministic pre-check the agent layer builds on. No LLM, no
    network, no subprocess.
    """
    return [check_requirement(req, profile) for req in spec_requirements]
