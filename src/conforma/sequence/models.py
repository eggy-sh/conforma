"""The sequence-domain data model: layouts, tracks, clips, and results.

These dataclasses mirror :mod:`conforma.models` exactly in spirit — frozen,
dependency-free (no pydantic, **no OTIO import**), and JSON-serializable via
``as_dict`` so the CLI's ``sequence ... --json`` output is a pure projection of
them. The OTIO ``Timeline`` is never carried here; :mod:`conforma.sequence.extract`
projects it into the lightweight :class:`SequenceLayout` payload first, and every
downstream module (rules, report, agent, CLI) speaks only this shape.

Keeping the model here lets the sequence modules depend on one stable vocabulary
without importing each other, just like the v0.1 ``conforma.models`` does for the
media path. The result types (:class:`SeqCheckStatus`, :class:`SeqRuleResult`,
:class:`SequenceReport`) mirror ``CheckStatus`` / ``RuleResult`` /
``ConformanceReport`` — same ``.conformant`` / ``.counts()`` conventions — so the
two report shapes are interchangeable to a consumer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SeqCheckStatus(StrEnum):
    """The outcome of evaluating one sequence rule against a layout.

    ``str``-valued so it serializes to a plain string in ``--json`` output, and
    intentionally identical in values to :class:`conforma.models.CheckStatus`.
    """

    PASS = "pass"
    FAIL = "fail"
    #: The layout did not carry the field this rule needs (e.g. no slate clip, no
    #: resolvable roles). Distinct from FAIL: conformance could not be proven.
    UNKNOWN = "unknown"


# --- Extracted sequence payload --------------------------------------------


@dataclass(frozen=True)
class ClipInfo:
    """One clip on a track, projected from an ``otio.schema.Clip``.

    Times are in seconds (from ``RationalTime.to_seconds()``); ``lane`` is the
    clip's stacking lane index where the source format carries one (FCPXML), else
    ``0``. Pure data — no OTIO object is retained.
    """

    name: str
    start_seconds: float
    duration_seconds: float
    lane: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start_seconds": self.start_seconds,
            "duration_seconds": self.duration_seconds,
            "lane": self.lane,
        }


@dataclass(frozen=True)
class TrackInfo:
    """One track (video or audio) projected from an ``otio.schema.Track``.

    ``kind`` is ``"video"`` or ``"audio"``; ``index`` is the track's position
    within its kind (1-based, in document order); ``enabled`` mirrors OTIO's
    native enable/mute flag (a muted reference track has ``enabled=False``).
    ``role`` is the deterministic role inferred by
    :mod:`conforma.sequence.extract` (``"reference"`` / ``"me"`` / ``"dialogue"``
    / ``"music"`` / ``"unknown"``), which the agent may later refine for tracks
    it left ``"unknown"``.
    """

    name: str
    kind: str  # "video" | "audio"
    index: int
    enabled: bool = True
    role: str = "unknown"
    clips: list[ClipInfo] = field(default_factory=list)
    total_duration_seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "index": self.index,
            "enabled": self.enabled,
            "role": self.role,
            "clips": [c.as_dict() for c in self.clips],
            "total_duration_seconds": self.total_duration_seconds,
        }


@dataclass(frozen=True)
class SequenceLayout:
    """The lightweight, JSON-serializable projection of an OTIO timeline.

    Everything the deterministic rules need, with **no** OTIO object retained:
    the timeline name, frame rate, track counts, the ordered tracks (each with
    its clips and inferred role), and the identified slate clip and its duration.
    ``source`` records provenance (the path the timeline was read from).
    """

    timeline_name: str
    frame_rate: float | None
    tracks: list[TrackInfo]
    slate_clip: ClipInfo | None = None
    slate_duration_seconds: float | None = None
    source: str = ""

    @property
    def track_count(self) -> int:
        """Total number of tracks (video + audio)."""
        return len(self.tracks)

    @property
    def video_track_count(self) -> int:
        """Number of video tracks."""
        return sum(1 for t in self.tracks if t.kind == "video")

    @property
    def audio_track_count(self) -> int:
        """Number of audio tracks."""
        return sum(1 for t in self.tracks if t.kind == "audio")

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable view of the whole layout."""
        return {
            "timeline_name": self.timeline_name,
            "frame_rate": self.frame_rate,
            "track_count": self.track_count,
            "video_track_count": self.video_track_count,
            "audio_track_count": self.audio_track_count,
            "tracks": [t.as_dict() for t in self.tracks],
            "slate_clip": self.slate_clip.as_dict() if self.slate_clip is not None else None,
            "slate_duration_seconds": self.slate_duration_seconds,
            "source": self.source,
        }


# --- Results ----------------------------------------------------------------


@dataclass(frozen=True)
class SeqRuleResult:
    """The outcome of checking one sequence rule against a layout.

    Mirrors :class:`conforma.models.RuleResult`: ``actual`` is the value pulled
    from the layout (or ``None`` if absent), ``message`` is the human one-liner,
    and ``fix_hint`` is a short, deterministic remediation note (the sequence
    analogue of ``RuleResult.fix_command``).
    """

    key: str
    status: SeqCheckStatus
    expected: Any
    actual: Any
    message: str
    severity: str = "must"
    fix_hint: str = ""

    @property
    def passed(self) -> bool:
        """True iff this result is a PASS."""
        return self.status == SeqCheckStatus.PASS

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable view of this result."""
        return {
            "key": self.key,
            "status": str(self.status),
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
            "severity": self.severity,
            "fix_hint": self.fix_hint,
        }


@dataclass(frozen=True)
class SequenceReport:
    """The aggregate result of checking a layout against a delivery spec.

    Mirrors :class:`conforma.models.ConformanceReport` field-for-field in spirit
    (same ``.conformant`` / ``.counts()`` contract) so a consumer can treat both
    reports the same way. ``results`` preserves rule order; ``llm_summary`` holds
    the optional agent narrative and is empty for a purely deterministic run.
    """

    spec_name: str
    spec_version: str
    sequence_source: str
    results: list[SeqRuleResult]
    llm_summary: str = ""

    @property
    def conformant(self) -> bool:
        """True iff no blocking ("must") requirement failed."""
        return not any(
            r.status == SeqCheckStatus.FAIL and r.severity == "must" for r in self.results
        )

    @property
    def failures(self) -> list[SeqRuleResult]:
        """The FAIL results, in rule order."""
        return [r for r in self.results if r.status == SeqCheckStatus.FAIL]

    def counts(self) -> dict[str, int]:
        """A ``{status: count}`` tally over :attr:`results`."""
        tally = {str(s): 0 for s in SeqCheckStatus}
        for r in self.results:
            tally[str(r.status)] += 1
        return tally

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable view of the whole report."""
        return {
            "spec_name": self.spec_name,
            "spec_version": self.spec_version,
            "sequence_source": self.sequence_source,
            "conformant": self.conformant,
            "counts": self.counts(),
            "llm_summary": self.llm_summary,
            "results": [r.as_dict() for r in self.results],
        }
