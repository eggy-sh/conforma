"""Normalize probe JSON (ffprobe or MediaInfo) into a :class:`MediaProfile`.

The deterministic core only ever sees a normalized :class:`~conforma.models.MediaProfile`,
so the rules never branch on probe source. :func:`normalize_probe` auto-detects
ffprobe vs MediaInfo JSON and maps either onto the same shape, parsing the
fiddly bits (rational frame rates like ``"24000/1001"``, MediaInfo's stringly
typed numbers, channel layouts). :func:`load_probe` reads such JSON from a file.

Shelling out is **optional and never required**: :func:`probe_media` runs a real
``ffprobe`` if one is on ``PATH`` (guarded by :func:`ffprobe_available`), but the
whole test suite and CI run purely off committed fixture JSON.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from enum import StrEnum
from typing import Any

from .errors import ProbeError
from .models import AudioProfile, MediaProfile, VideoProfile

#: Pixel-format suffix -> implied luma bit depth, for probes that report a
#: pixel format but no explicit bit depth.
_PIX_FMT_DEPTHS: list[tuple[str, int]] = [
    ("16le", 16),
    ("16be", 16),
    ("12le", 12),
    ("12be", 12),
    ("10le", 10),
    ("10be", 10),
    ("p10", 10),
    ("p12", 12),
    ("p16", 16),
]


class ProbeSource(StrEnum):
    """Which probe tool produced a JSON payload."""

    FFPROBE = "ffprobe"
    MEDIAINFO = "mediainfo"
    UNKNOWN = "unknown"


def detect_probe_source(data: dict[str, Any]) -> ProbeSource:
    """Classify a parsed probe payload as ffprobe, MediaInfo, or unknown.

    ffprobe ``-print_format json`` has top-level ``"streams"`` / ``"format"``;
    MediaInfo ``--Output=JSON`` has a top-level ``"media"`` with a ``"track"``
    list. Used internally by :func:`normalize_probe`; exposed for callers that
    want to branch without re-parsing.
    """
    if not isinstance(data, dict):
        return ProbeSource.UNKNOWN
    media = data.get("media")
    if isinstance(media, dict) and isinstance(media.get("track"), list):
        return ProbeSource.MEDIAINFO
    if "streams" in data or "format" in data:
        return ProbeSource.FFPROBE
    return ProbeSource.UNKNOWN


def parse_frame_rate(value: Any) -> float | None:
    """Parse a frame rate into a float fps.

    Accepts an ffprobe rational string (``"24000/1001"`` -> ``23.976...``), a
    plain number, or a numeric string. Returns ``None`` for missing / zero /
    unparseable input (e.g. ffprobe's ``"0/0"``) so a rule can report UNKNOWN.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if "/" in text:
        num_s, _, den_s = text.partition("/")
        try:
            num = float(num_s)
            den = float(den_s)
        except ValueError:
            return None
        if den == 0 or num == 0:
            return None
        return num / den
    try:
        rate = float(text)
    except ValueError:
        return None
    return rate if rate else None


def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bit_depth_from_pix_fmt(pix_fmt: str | None) -> int | None:
    if not pix_fmt:
        return None
    lowered = pix_fmt.lower()
    for suffix, depth in _PIX_FMT_DEPTHS:
        if suffix in lowered:
            return depth
    return None


def _ffprobe_scan_type(field_order: Any) -> str | None:
    if not isinstance(field_order, str):
        return None
    fo = field_order.strip().lower()
    if not fo or fo == "unknown":
        return None
    if fo in ("progressive", "p"):
        return "progressive"
    if fo in ("tt", "bb", "tb", "bt", "interlaced", "i"):
        return "interlaced"
    return None


def _normalize_ffprobe(data: dict[str, Any], source: str) -> MediaProfile:
    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    video: VideoProfile | None = None
    audios: list[AudioProfile] = []

    for stream in streams:
        if not isinstance(stream, dict):
            continue
        codec_type = stream.get("codec_type")
        if codec_type == "video" and video is None:
            pix_fmt = stream.get("pix_fmt")
            bit_depth = _to_int(stream.get("bits_per_raw_sample"))
            if bit_depth is None:
                bit_depth = _bit_depth_from_pix_fmt(pix_fmt)
            frame_rate = parse_frame_rate(
                stream.get("r_frame_rate") or stream.get("avg_frame_rate")
            )
            video = VideoProfile(
                codec=stream.get("codec_name"),
                width=_to_int(stream.get("width")),
                height=_to_int(stream.get("height")),
                frame_rate=frame_rate,
                bit_depth=bit_depth,
                pixel_format=pix_fmt,
                color_primaries=stream.get("color_primaries"),
                scan_type=_ffprobe_scan_type(stream.get("field_order")),
            )
        elif codec_type == "audio":
            tags = stream.get("tags") or {}
            language = tags.get("language") if isinstance(tags, dict) else None
            audios.append(
                AudioProfile(
                    codec=stream.get("codec_name"),
                    channels=_to_int(stream.get("channels")),
                    sample_rate=_to_int(stream.get("sample_rate")),
                    bit_depth=_to_int(stream.get("bits_per_sample")) or None,
                    language=language,
                )
            )

    return MediaProfile(
        container=fmt.get("format_name"),
        video=video,
        audio=audios,
        duration_seconds=_to_float(fmt.get("duration")),
        source=source or "ffprobe",
        raw=data,
    )


def _mediainfo_scan_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    st = value.strip().lower()
    if not st:
        return None
    if st.startswith("progress"):
        return "progressive"
    if st.startswith("interlac") or st in ("mbaff", "paff"):
        return "interlaced"
    return None


def _normalize_mediainfo(data: dict[str, Any], source: str) -> MediaProfile:
    tracks = data["media"]["track"]
    general: dict[str, Any] = {}
    video: VideoProfile | None = None
    audios: list[AudioProfile] = []

    for track in tracks:
        if not isinstance(track, dict):
            continue
        ttype = str(track.get("@type", "")).lower()
        if ttype == "general":
            general = track
        elif ttype == "video" and video is None:
            video = VideoProfile(
                codec=track.get("Format"),
                width=_to_int(track.get("Width")),
                height=_to_int(track.get("Height")),
                frame_rate=parse_frame_rate(track.get("FrameRate")),
                bit_depth=_to_int(track.get("BitDepth")),
                pixel_format=track.get("ChromaSubsampling"),
                color_primaries=track.get("colour_primaries") or track.get("ColorPrimaries"),
                scan_type=_mediainfo_scan_type(track.get("ScanType")),
            )
        elif ttype == "audio":
            audios.append(
                AudioProfile(
                    codec=track.get("Format"),
                    channels=_to_int(track.get("Channels")),
                    sample_rate=_to_int(track.get("SamplingRate")),
                    bit_depth=_to_int(track.get("BitDepth")) or None,
                    language=track.get("Language"),
                )
            )

    container = general.get("FileExtension") or general.get("Format")
    return MediaProfile(
        container=container,
        video=video,
        audio=audios,
        duration_seconds=_to_float(general.get("Duration")),
        source=source or "mediainfo",
        raw=data,
    )


def normalize_probe(data: dict[str, Any], *, source: str = "") -> MediaProfile:
    """Normalize parsed ffprobe or MediaInfo JSON into a :class:`MediaProfile`.

    Auto-detects the probe source (see :func:`detect_probe_source`). Picks the
    first video stream/track and every audio stream/track, parsing frame rate,
    bit depth, channel count, sample rate, container, and duration. Fields the
    probe omits become ``None`` (never guessed). Raises
    :class:`~conforma.errors.ProbeError` if the payload matches neither known
    shape. ``source`` overrides the recorded provenance string.
    """
    detected = detect_probe_source(data)
    if detected is ProbeSource.FFPROBE:
        return _normalize_ffprobe(data, source)
    if detected is ProbeSource.MEDIAINFO:
        return _normalize_mediainfo(data, source)
    raise ProbeError(
        "Unrecognized probe payload: expected ffprobe JSON (top-level 'streams'/"
        "'format') or MediaInfo JSON (top-level 'media.track')."
    )


def load_probe(path: str) -> MediaProfile:
    """Read probe JSON from ``path`` and normalize it.

    Raises :class:`~conforma.errors.ProbeError` on a missing file, invalid JSON,
    or an unrecognized probe shape. The returned profile's ``source`` records
    ``path``.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise ProbeError(f"Could not read probe file {path!r}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"Invalid JSON in probe file {path!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProbeError(f"Probe file {path!r} did not contain a JSON object.")
    return normalize_probe(data, source=path)


def ffprobe_available() -> bool:
    """Return True iff an ``ffprobe`` executable is discoverable on ``PATH``.

    Pure capability check (``shutil.which``); never runs ffprobe. The CLI uses
    this to decide whether a non-JSON media path can be auto-probed.
    """
    return shutil.which("ffprobe") is not None


def probe_media(path: str, *, timeout: float = 30.0) -> MediaProfile:
    """Run a real ``ffprobe`` on a media file and normalize its JSON output.

    This is the **only** function that shells out, and it is never on the
    hermetic path. Raises :class:`~conforma.errors.ProbeError` if ffprobe is
    absent, exits non-zero, times out, or emits unparseable JSON. Tests cover
    this by monkeypatching the subprocess boundary, not by invoking ffmpeg.
    """
    if not ffprobe_available():
        raise ProbeError(
            "ffprobe is not available on PATH; pass a probe JSON file instead, or "
            "install ffmpeg/ffprobe."
        )
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffprobe timed out after {timeout}s on {path!r}.") from exc
    except OSError as exc:
        raise ProbeError(f"Could not run ffprobe on {path!r}: {exc}") from exc
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise ProbeError(
            f"ffprobe exited {completed.returncode} on {path!r}: {stderr or 'no stderr'}"
        )
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe emitted unparseable JSON for {path!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProbeError(f"ffprobe output for {path!r} was not a JSON object.")
    return normalize_probe(data, source=path)
