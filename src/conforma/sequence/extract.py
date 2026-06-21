"""Project an OTIO ``Timeline`` into the lightweight :class:`SequenceLayout`.

This is pure, deterministic projection: walk the timeline's tracks in document
order, read clip ``name`` / ``source_range`` (start + duration via
``RationalTime.to_seconds()``), compute per-track totals, find the slate (the
first clip on the first video track, by position), and infer a deterministic
``role`` for each track from **literal keyword matching only** (no thresholds, no
fuzziness, no model). The fuzzy fallback for tracks this module marks
``"unknown"`` lives in :mod:`conforma.sequence.agent` and only fills the gaps.

The OTIO object is touched here and only here-adjacent (this module reads OTIO
schema attributes but imports nothing OTIO-specific beyond attribute access),
producing the dependency-free :class:`SequenceLayout` everything downstream uses.
"""

from __future__ import annotations

from typing import Any

from .models import ClipInfo, SequenceLayout, TrackInfo

#: Role -> the set of lowercase tokens that, found as a whole word or substring in
#: a track or clip name, deterministically assign that role. Order matters:
#: :func:`infer_role_deterministic` checks roles in this dict's iteration order and
#: returns the first hit, so the most specific roles come first.
ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    # A scratch/reference/temp stem that must be muted on delivery.
    "reference": ("ref", "scratch", "temp", "2pop", "pop", "guide", "slate guide"),
    # Music & effects stem.
    "me": ("m&e", "me", "music and effects", "fx stem"),
    # Dialogue / production sound.
    "dialogue": ("dialogue", "dialog", "dx", "prod sound", "production sound"),
    # Music stem.
    "music": ("music", "score", "mx"),
}


def _tokens(name: str) -> list[str]:
    """Split a track/clip name into lowercase word tokens for whole-word matching."""
    cleaned = []
    for ch in name.lower():
        cleaned.append(ch if ch.isalnum() or ch == "&" else " ")
    return "".join(cleaned).split()


def _keyword_hits(name: str, keyword: str) -> bool:
    """True if ``keyword`` matches ``name`` as a whole token or contained phrase.

    Multi-word keywords (``"m&e"``, ``"production sound"``) match as a substring
    of the normalized name; single-token keywords match a whole word so ``"me"``
    does not fire on ``"theme"`` or ``"timecode"``.
    """
    norm = " ".join(_tokens(name))
    kw = keyword.lower().strip()
    if " " in kw or "&" in kw:
        return kw in norm or kw in name.lower()
    return kw in _tokens(name)


def infer_role_deterministic(
    track_name: str,
    clip_names: list[str],
    *,
    extra_reference_keywords: tuple[str, ...] = (),
) -> str:
    """Infer a track's role from its name and clip names by literal keywords only.

    Returns one of ``"reference"`` / ``"me"`` / ``"dialogue"`` / ``"music"`` or
    ``"unknown"`` when no keyword fires. ``extra_reference_keywords`` lets a
    delivery spec extend the ``reference`` keyword set (e.g. a studio's house
    term). Deterministic and total: same inputs, same output, never raises.
    """
    haystacks = [track_name, *clip_names]

    # Spec-supplied reference keywords are checked first so a studio term wins.
    for kw in extra_reference_keywords:
        for name in haystacks:
            if _keyword_hits(name, kw):
                return "reference"

    for role, keywords in ROLE_KEYWORDS.items():
        for kw in keywords:
            for name in haystacks:
                if _keyword_hits(name, kw):
                    return role
    return "unknown"


def _kind_of(track: Any) -> str:
    """Map an OTIO track's ``kind`` to ``"video"`` / ``"audio"`` (default video)."""
    kind = getattr(track, "kind", "Video")
    return "audio" if str(kind).lower() == "audio" else "video"


def _clip_infos(track: Any) -> tuple[list[ClipInfo], float]:
    """Project a track's clips into :class:`ClipInfo` plus the summed duration."""
    import opentimelineio as otio

    clips: list[ClipInfo] = []
    cursor = 0.0
    total = 0.0
    for child in track:
        if not isinstance(child, otio.schema.Clip):
            # Gaps/transitions advance the cursor but are not clips.
            dur = _safe_duration(child)
            cursor += dur
            total += dur
            continue
        dur = _safe_duration(child)
        clips.append(
            ClipInfo(
                name=child.name or "",
                start_seconds=round(cursor, 6),
                duration_seconds=round(dur, 6),
                lane=_lane_of(child),
            )
        )
        cursor += dur
        total += dur
    return clips, round(total, 6)


def _safe_duration(child: Any) -> float:
    """Return a child's duration in seconds, or ``0.0`` if it has no range."""
    rng = getattr(child, "source_range", None)
    if rng is None:
        try:
            rng = child.range_in_parent()
        except Exception:
            return 0.0
    try:
        return float(rng.duration.to_seconds())
    except Exception:  # pragma: no cover - malformed range
        return 0.0


def _mapping_get(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a mapping-like object (``dict`` or OTIO ``AnyDictionary``).

    OTIO's ``metadata`` is an ``AnyDictionary`` — mapping-like but *not* a ``dict``
    subclass — so an ``isinstance(meta, dict)`` guard would silently drop every
    metadata lookup. We duck-type on ``.get`` instead.
    """
    if obj is None or not hasattr(obj, "get"):
        return default
    return obj.get(key, default)


def _lane_of(clip: Any) -> int:
    """Read a clip's FCPXML lane from metadata, defaulting to ``0``."""
    fcpx = _mapping_get(getattr(clip, "metadata", None), "fcpx_xml", {})
    lane = _mapping_get(fcpx, "lane")
    try:
        return int(lane)
    except (TypeError, ValueError):
        return 0


def _explicit_audio_role(track: Any, clips: list[Any]) -> str | None:
    """Surface an explicit FCPXML ``audioRole`` from track/clip metadata, if any.

    Returns the raw role string (lowercased) when present, else ``None``. This is
    a *deterministic* signal — it is read, not inferred. Handles OTIO's
    ``AnyDictionary`` metadata (not a ``dict`` subclass) via :func:`_mapping_get`.
    """
    sources = [track, *clips]
    for obj in sources:
        fcpx = _mapping_get(getattr(obj, "metadata", None), "fcpx_xml", {})
        for key in ("audioRole", "role", "audio_role"):
            value = _mapping_get(fcpx, key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
    return None


def _role_from_explicit(explicit: str) -> str:
    """Map an explicit FCPXML role string onto our role vocabulary."""
    e = explicit.lower()
    if any(tok in e for tok in ("ref", "scratch", "temp")):
        return "reference"
    if "dialog" in e or e in ("dx",):
        return "dialogue"
    if "music" in e or "score" in e:
        return "music"
    if "effect" in e or e in ("me", "m&e"):
        return "me"
    return "unknown"


def find_slate(tracks: list[TrackInfo]) -> ClipInfo | None:
    """Return the slate clip: the first clip on the first video track, by position.

    The slate is identified purely by structural position (front of the picture
    track), not by name — so it is found even when the editor named it oddly.
    Returns ``None`` when there is no video track or it has no clips.
    """
    for track in tracks:
        if track.kind == "video" and track.clips:
            return min(track.clips, key=lambda c: c.start_seconds)
    return None


def extract_layout(timeline: Any, *, source: str = "") -> SequenceLayout:
    """Project an ``otio.schema.Timeline`` into a :class:`SequenceLayout`.

    Walks tracks in document order, projecting each into a :class:`TrackInfo`
    (with its clips and a deterministically inferred ``role``), identifies the
    slate (first clip on the first video track) and its duration, and returns the
    lightweight payload. ``extra_reference_keywords`` is *not* taken here — role
    inference uses the shipped :data:`ROLE_KEYWORDS`; spec-supplied keyword
    extension is applied by the rules layer. Pure and deterministic.
    """
    import opentimelineio as otio

    track_infos: list[TrackInfo] = []
    video_idx = 0
    audio_idx = 0

    for raw_track in timeline.tracks:
        if not isinstance(raw_track, otio.schema.Track):  # pragma: no cover - defensive
            continue
        kind = _kind_of(raw_track)
        if kind == "video":
            video_idx += 1
            index = video_idx
        else:
            audio_idx += 1
            index = audio_idx

        otio_clips = [c for c in raw_track if isinstance(c, otio.schema.Clip)]
        clips, total = _clip_infos(raw_track)
        clip_names = [c.name for c in clips]

        # Deterministic role: explicit FCPXML role first, then keyword inference.
        role = "unknown"
        explicit = _explicit_audio_role(raw_track, otio_clips)
        if explicit is not None:
            role = _role_from_explicit(explicit)
        if role == "unknown":
            role = infer_role_deterministic(raw_track.name or "", clip_names)

        track_infos.append(
            TrackInfo(
                name=raw_track.name or "",
                kind=kind,
                index=index,
                enabled=bool(getattr(raw_track, "enabled", True)),
                role=role,
                clips=clips,
                total_duration_seconds=total,
            )
        )

    slate = find_slate(track_infos)
    slate_duration = slate.duration_seconds if slate is not None else None

    frame_rate = _global_rate(timeline)

    return SequenceLayout(
        timeline_name=timeline.name or "",
        frame_rate=frame_rate,
        tracks=track_infos,
        slate_clip=slate,
        slate_duration_seconds=slate_duration,
        source=source,
    )


def _global_rate(timeline: Any) -> float | None:
    """Best-effort global frame rate from the timeline's global_start_time."""
    gst = getattr(timeline, "global_start_time", None)
    if gst is not None:
        try:
            return float(gst.rate)
        except Exception:  # pragma: no cover
            return None
    # Fall back to the rate of the first clip's source range we can find.
    import opentimelineio as otio

    for track in timeline.tracks:
        if not isinstance(track, otio.schema.Track):  # pragma: no cover - defensive
            continue
        for child in track:
            rng = getattr(child, "source_range", None)
            if rng is not None:
                try:
                    return float(rng.duration.rate)
                except Exception:  # pragma: no cover
                    return None
    return None
