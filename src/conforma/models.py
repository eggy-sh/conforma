"""The core data model: specs, normalized media profiles, and results.

These dataclasses are the shared vocabulary every other module speaks. They are
plain, dependency-free (no pydantic), and JSON-serializable via ``as_dict`` so
the CLI's ``--json`` output is a pure projection of them. Keeping the model here
lets :mod:`conforma.spec`, :mod:`conforma.probe`, :mod:`conforma.rules`,
:mod:`conforma.fixes`, and :mod:`conforma.agent` all depend on one stable shape
without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CheckStatus(StrEnum):
    """The outcome of evaluating one requirement against a media profile.

    ``str``-valued so it serializes to a plain string in ``--json`` output.
    """

    PASS = "pass"
    FAIL = "fail"
    #: The probe did not carry the field this requirement needs (e.g. no bit
    #: depth reported). Distinct from FAIL: we could not prove conformance.
    UNKNOWN = "unknown"


# --- Delivery spec ---------------------------------------------------------


@dataclass(frozen=True)
class Requirement:
    """One checkable line item of a delivery spec.

    ``key`` selects the :class:`~conforma.rules.Rule` that evaluates it (e.g.
    ``"resolution"``, ``"frame_rate"``, ``"video_codec"``, ``"bit_depth"``,
    ``"audio_channels"``, ``"container"``). ``expected`` holds the rule-specific
    target (a scalar or a list of accepted values). ``tolerance`` is an optional
    numeric slack (used by e.g. frame-rate checks). ``description`` is
    human-facing prose for the report; ``severity`` lets a spec mark a
    requirement advisory rather than blocking.
    """

    key: str
    expected: Any
    tolerance: float | None = None
    description: str = ""
    severity: str = "must"  # "must" (blocking) | "should" (advisory)

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable view of this requirement."""
        return {
            "key": self.key,
            "expected": self.expected,
            "tolerance": self.tolerance,
            "description": self.description,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class Spec:
    """A parsed, validated delivery spec.

    ``name`` / ``version`` identify the spec (e.g. "Netflix HD ProRes", "1.0");
    ``container`` is the top-level convenience for the expected wrapper; and
    ``requirements`` is the ordered list of checkable items. Built only via
    :func:`conforma.spec.parse_spec` / :func:`conforma.spec.load_spec`, which
    guarantee every requirement key is known.
    """

    name: str
    version: str
    requirements: list[Requirement]
    description: str = ""
    source: str = ""  # provenance: preset name or file path

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable view of this spec."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "source": self.source,
            "requirements": [r.as_dict() for r in self.requirements],
        }


# --- Normalized media profile ----------------------------------------------


@dataclass(frozen=True)
class VideoProfile:
    """The video stream facts conforma checks against.

    Normalized from ffprobe's first video stream or MediaInfo's video track.
    Fields that the probe did not report are ``None`` (so a rule can return
    :attr:`CheckStatus.UNKNOWN` rather than a misleading FAIL).
    """

    codec: str | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None  # frames per second, as a float
    bit_depth: int | None = None
    pixel_format: str | None = None
    color_primaries: str | None = None
    scan_type: str | None = None  # "progressive" | "interlaced"

    def as_dict(self) -> dict[str, Any]:
        return {
            "codec": self.codec,
            "width": self.width,
            "height": self.height,
            "frame_rate": self.frame_rate,
            "bit_depth": self.bit_depth,
            "pixel_format": self.pixel_format,
            "color_primaries": self.color_primaries,
            "scan_type": self.scan_type,
        }


@dataclass(frozen=True)
class AudioProfile:
    """The audio stream facts conforma checks against.

    Normalized from one ffprobe audio stream or MediaInfo audio track. A media
    file may carry several; :class:`MediaProfile` holds them all.
    """

    codec: str | None = None
    channels: int | None = None
    sample_rate: int | None = None  # Hz
    bit_depth: int | None = None
    language: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "codec": self.codec,
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "language": self.language,
        }


@dataclass(frozen=True)
class MediaProfile:
    """The normalized, probe-source-agnostic view of one media file.

    Both ffprobe and MediaInfo JSON normalize into this single shape, so the
    rules never branch on probe source. ``raw`` keeps the original parsed JSON
    for debugging / agent context but is never required by the deterministic
    rules.
    """

    container: str | None = None
    video: VideoProfile | None = None
    audio: list[AudioProfile] = field(default_factory=list)
    duration_seconds: float | None = None
    source: str = ""  # "ffprobe" | "mediainfo" | file path
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable view, excluding ``raw`` by default."""
        return {
            "container": self.container,
            "video": self.video.as_dict() if self.video is not None else None,
            "audio": [a.as_dict() for a in self.audio],
            "duration_seconds": self.duration_seconds,
            "source": self.source,
        }


# --- Results ----------------------------------------------------------------


@dataclass(frozen=True)
class RuleResult:
    """The outcome of checking one :class:`Requirement` against a profile.

    ``actual`` is the value pulled from the media profile (or ``None`` if
    absent). ``fix_command`` is the suggested ``ffmpeg`` invocation that would
    bring the file into conformance; it is populated for FAILs and empty for
    PASS/UNKNOWN. ``message`` is the human-facing one-liner shown in the report.
    """

    key: str
    status: CheckStatus
    expected: Any
    actual: Any
    message: str
    severity: str = "must"
    fix_command: str = ""

    @property
    def passed(self) -> bool:
        """True iff this result is a PASS."""
        return self.status == CheckStatus.PASS

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable view of this result."""
        return {
            "key": self.key,
            "status": str(self.status),
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
            "severity": self.severity,
            "fix_command": self.fix_command,
        }


@dataclass(frozen=True)
class ConformanceReport:
    """The aggregate result of checking a profile against a spec.

    ``results`` preserves spec requirement order. ``conformant`` is True iff no
    blocking ("must") requirement FAILed and none are UNKNOWN-blocking per the
    chosen policy. ``llm_summary`` holds the optional natural-language narrative
    produced by the :mod:`conforma.agent`; it is empty for a purely deterministic
    run.
    """

    spec_name: str
    spec_version: str
    media_source: str
    results: list[RuleResult]
    llm_summary: str = ""

    @property
    def conformant(self) -> bool:
        """True iff no blocking ("must") requirement failed."""
        return not any(r.status == CheckStatus.FAIL and r.severity == "must" for r in self.results)

    @property
    def failures(self) -> list[RuleResult]:
        """The FAIL results, in spec order."""
        return [r for r in self.results if r.status == CheckStatus.FAIL]

    def counts(self) -> dict[str, int]:
        """A ``{status: count}`` tally over :attr:`results`."""
        tally = {str(s): 0 for s in CheckStatus}
        for r in self.results:
            tally[str(r.status)] += 1
        return tally

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable view of the whole report (the ``--json`` shape)."""
        return {
            "spec_name": self.spec_name,
            "spec_version": self.spec_version,
            "media_source": self.media_source,
            "conformant": self.conformant,
            "counts": self.counts(),
            "llm_summary": self.llm_summary,
            "results": [r.as_dict() for r in self.results],
        }
