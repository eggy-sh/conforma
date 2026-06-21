"""BONUS deterministic corrector: emit a fixed OTIO timeline from a report.

:func:`apply_fixes` mutates a **deep copy** of the source timeline so the input
is never touched, applying only OTIO-native, lossless corrections:

* For every ``reference_audio_muted`` FAIL it sets the offending audio track's
  ``.enabled = False`` — the OTIO-native mute.
* For a ``slate_duration`` FAIL it annotates the slate clip's metadata with a
  ``conforma_flag`` note describing required vs actual duration. It *flags*; it
  does not fabricate frames.

:func:`fix_sequence` is the one-call entry point: apply fixes and write the
corrected timeline to ``path`` via :func:`conforma.sequence.otio_io.write_timeline`.
No LLM, no media, no network — pure OTIO object manipulation. ``otio_json`` output
preserves track names + ``enabled`` deterministically; FCPXML output is best-effort
and documented as lossy for track names.
"""

from __future__ import annotations

from typing import Any

from .models import SeqCheckStatus, SequenceLayout, SequenceReport
from .otio_io import write_timeline


def _result_by_key(report: SequenceReport) -> dict[str, Any]:
    return {r.key: r for r in report.results}


def _reference_track_names(report: SequenceReport, layout: SequenceLayout) -> set[str]:
    """Names of reference audio tracks that were flagged not-muted (FAIL).

    Read off the layout's roles (the same the verdict used), restricted to the
    failing ``reference_audio_muted`` rule so we only mute what the report flagged.
    """
    by_key = _result_by_key(report)
    result = by_key.get("reference_audio_muted")
    if result is None or result.status != SeqCheckStatus.FAIL:
        return set()
    return {
        t.name for t in layout.tracks if t.kind == "audio" and t.role == "reference" and t.enabled
    }


def apply_fixes(timeline: Any, layout: SequenceLayout, report: SequenceReport) -> Any:
    """Return a corrected **deep copy** of ``timeline`` per the report's FAILs.

    Mutates only the copy: mutes (``enabled=False``) every reference audio track
    flagged not-muted, and annotates the slate clip with a ``conforma_flag`` note
    when the slate duration FAILed. Returns the corrected timeline; the caller
    writes it. Deterministic and OTIO-native; never fabricates media.
    """
    import opentimelineio as otio

    corrected = timeline.deepcopy()
    by_key = _result_by_key(report)

    # 1) Mute flagged reference audio tracks.
    ref_names = _reference_track_names(report, layout)
    if ref_names:
        for track in corrected.tracks:
            if not isinstance(track, otio.schema.Track):  # pragma: no cover - defensive
                continue
            if str(getattr(track, "kind", "")).lower() == "audio" and track.name in ref_names:
                track.enabled = False

    # 2) Annotate the slate clip when its duration FAILed (flag, don't fabricate).
    slate_result = by_key.get("slate_duration")
    if (
        slate_result is not None
        and slate_result.status == SeqCheckStatus.FAIL
        and layout.slate_clip is not None
    ):
        slate_name = layout.slate_clip.name
        for track in corrected.tracks:
            if not isinstance(track, otio.schema.Track):  # pragma: no cover - defensive
                continue
            if str(getattr(track, "kind", "")).lower() != "video":
                continue
            for child in track:
                if isinstance(child, otio.schema.Clip) and child.name == slate_name:
                    note = (
                        f"slate duration {slate_result.actual}s does not match required "
                        f"{slate_result.expected}s"
                    )
                    child.metadata["conforma_flag"] = note
                    break
            break  # only the first video track holds the slate

    return corrected


def fix_sequence(
    timeline: Any,
    layout: SequenceLayout,
    report: SequenceReport,
    out_path: str,
) -> Any:
    """Apply fixes and write the corrected timeline to ``out_path``.

    Convenience wrapper over :func:`apply_fixes` +
    :func:`conforma.sequence.otio_io.write_timeline`. Returns the corrected
    timeline (so a caller can also round-trip / inspect it). Raises
    :class:`~conforma.sequence.errors.SequenceError` if the output adapter is
    missing or the write fails.
    """
    corrected = apply_fixes(timeline, layout, report)
    write_timeline(corrected, out_path)
    return corrected
