"""Deterministic sequence rule pre-checks — the heart of the sequence path.

Given a :class:`~conforma.sequence.models.SequenceLayout` and a
:class:`~conforma.sequence.delivery_spec.DeliverySpec`, produce ordered
:class:`~conforma.sequence.models.SeqRuleResult` objects with **no LLM**. The full
pass/fail verdict is computed here; the agent layer only narrates and (optionally)
fills ambiguous roles the deterministic extractor left ``"unknown"``.

Every check is total and pure: when the layout lacks the field a rule needs (no
slate clip, no resolvable roles, no spec field declared), it returns
:attr:`~conforma.sequence.models.SeqCheckStatus.UNKNOWN`, never an exception.
"""

from __future__ import annotations

from .delivery_spec import DeliverySpec
from .extract import infer_role_deterministic
from .models import SeqCheckStatus, SeqRuleResult, SequenceLayout, TrackInfo


def _as_int_list(value: int | list[int]) -> list[int]:
    return list(value) if isinstance(value, list) else [value]


def _resolve_reference_tracks(layout: SequenceLayout, spec: DeliverySpec) -> list[TrackInfo]:
    """Return audio tracks whose role resolves to ``"reference"``.

    Uses the role already on each track (deterministic, plus any agent-supplied
    fuzzy roles merged in upstream). When the spec extends the reference keyword
    set, re-runs the deterministic keyword match for that track so a studio's
    house term is honored without mutating the layout.
    """
    refs: list[TrackInfo] = []
    extra = spec.reference_role_keywords
    for track in layout.tracks:
        if track.kind != "audio":
            continue
        role = track.role
        if role == "unknown" and extra:
            clip_names = [c.name for c in track.clips]
            role = infer_role_deterministic(track.name, clip_names, extra_reference_keywords=extra)
        if role == "reference":
            refs.append(track)
    return refs


def check_slate_present(layout: SequenceLayout, spec: DeliverySpec) -> SeqRuleResult:
    """Check that a slate clip exists when the spec requires one.

    UNKNOWN when the spec does not declare ``slate.required``. PASS when a slate
    is present (or not required); FAIL when required but absent.
    """
    required = spec.slate_required
    if required is None:
        return SeqRuleResult(
            key="slate_present",
            status=SeqCheckStatus.UNKNOWN,
            expected=None,
            actual=layout.slate_clip is not None,
            message="Spec does not declare whether a slate is required.",
        )
    present = layout.slate_clip is not None
    if not required:
        return SeqRuleResult(
            key="slate_present",
            status=SeqCheckStatus.PASS,
            expected=False,
            actual=present,
            message="Slate is not required by the spec.",
        )
    status = SeqCheckStatus.PASS if present else SeqCheckStatus.FAIL
    message = (
        f"Slate clip present at head of the picture track ({layout.slate_clip.name!r})."
        if present
        else "No slate clip found at the head of the first video track."
    )
    return SeqRuleResult(
        key="slate_present",
        status=status,
        expected=True,
        actual=present,
        message=message,
        fix_hint="" if present else "Add a slate clip at the head of the first video track.",
    )


def check_slate_duration(layout: SequenceLayout, spec: DeliverySpec) -> SeqRuleResult:
    """Check the slate duration is within ``tolerance_seconds`` of the spec value.

    UNKNOWN when the spec declares no slate duration, or the layout has no slate.
    FAIL when present but off by more than the tolerance (e.g. 2 s vs required
    5 s); PASS otherwise.
    """
    expected = spec.slate_duration_seconds
    if expected is None:
        return SeqRuleResult(
            key="slate_duration",
            status=SeqCheckStatus.UNKNOWN,
            expected=None,
            actual=layout.slate_duration_seconds,
            message="Spec does not declare a required slate duration.",
        )
    actual = layout.slate_duration_seconds
    if actual is None:
        return SeqRuleResult(
            key="slate_duration",
            status=SeqCheckStatus.UNKNOWN,
            expected=expected,
            actual=None,
            message="No slate clip found, so its duration cannot be checked.",
        )
    tol = spec.slate_tolerance_seconds
    within = abs(actual - expected) <= tol
    status = SeqCheckStatus.PASS if within else SeqCheckStatus.FAIL
    if within:
        message = f"Slate duration {actual:g}s within {tol:g}s of required {expected:g}s."
        fix_hint = ""
    else:
        message = f"Slate duration {actual:g}s is not within {tol:g}s of required {expected:g}s."
        fix_hint = f"Trim or extend the slate clip to {expected:g}s (±{tol:g}s)."
    return SeqRuleResult(
        key="slate_duration",
        status=status,
        expected=expected,
        actual=round(actual, 3),
        message=message,
        fix_hint=fix_hint,
    )


def check_reference_audio_muted(layout: SequenceLayout, spec: DeliverySpec) -> SeqRuleResult:
    """Every reference/scratch audio track must be muted (``enabled=False``).

    UNKNOWN when the spec does not require it, or no audio track resolves to the
    ``reference`` role. FAIL when any reference track is still enabled; PASS when
    all reference tracks are muted.
    """
    if not spec.reference_audio_must_be_muted:
        return SeqRuleResult(
            key="reference_audio_muted",
            status=SeqCheckStatus.UNKNOWN,
            expected=None,
            actual=None,
            message="Spec does not require reference audio to be muted.",
        )
    refs = _resolve_reference_tracks(layout, spec)
    if not refs:
        return SeqRuleResult(
            key="reference_audio_muted",
            status=SeqCheckStatus.UNKNOWN,
            expected="all reference tracks muted",
            actual=None,
            message="No audio track resolves to the 'reference' role.",
        )
    live = [t for t in refs if t.enabled]
    status = SeqCheckStatus.PASS if not live else SeqCheckStatus.FAIL
    ref_names = [t.name for t in refs]
    if not live:
        message = f"All {len(refs)} reference audio track(s) are muted: {ref_names}."
        fix_hint = ""
    else:
        live_names = [t.name for t in live]
        message = f"Reference audio track(s) still enabled (not muted): {live_names}."
        fix_hint = f"Mute (disable) the reference track(s): {live_names}."
    return SeqRuleResult(
        key="reference_audio_muted",
        status=status,
        expected="all reference tracks muted",
        actual=ref_names if live else "all muted",
        message=message,
        fix_hint=fix_hint,
    )


def check_video_track_count(layout: SequenceLayout, spec: DeliverySpec) -> SeqRuleResult:
    """Check the video track count matches the spec (an int or one of a list).

    UNKNOWN when the spec declares no expected video track count.
    """
    expected = spec.expected_video_tracks
    if expected is None:
        return SeqRuleResult(
            key="video_track_count",
            status=SeqCheckStatus.UNKNOWN,
            expected=None,
            actual=layout.video_track_count,
            message="Spec does not declare an expected video track count.",
        )
    actual = layout.video_track_count
    candidates = _as_int_list(expected)
    status = SeqCheckStatus.PASS if actual in candidates else SeqCheckStatus.FAIL
    shown = "/".join(str(c) for c in candidates)
    if status == SeqCheckStatus.PASS:
        message = f"Video track count {actual} matches required {shown}."
        fix_hint = ""
    else:
        message = f"Video track count {actual} does not match required {shown}."
        fix_hint = f"Adjust the timeline to have {shown} video track(s)."
    return SeqRuleResult(
        key="video_track_count",
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        fix_hint=fix_hint,
    )


def check_audio_track_count(layout: SequenceLayout, spec: DeliverySpec) -> SeqRuleResult:
    """Check the audio track count matches the spec (an int or one of a list).

    UNKNOWN when the spec declares no expected audio track count.
    """
    expected = spec.expected_audio_tracks
    if expected is None:
        return SeqRuleResult(
            key="audio_track_count",
            status=SeqCheckStatus.UNKNOWN,
            expected=None,
            actual=layout.audio_track_count,
            message="Spec does not declare an expected audio track count.",
        )
    actual = layout.audio_track_count
    candidates = _as_int_list(expected)
    status = SeqCheckStatus.PASS if actual in candidates else SeqCheckStatus.FAIL
    shown = "/".join(str(c) for c in candidates)
    if status == SeqCheckStatus.PASS:
        message = f"Audio track count {actual} matches required {shown}."
        fix_hint = ""
    else:
        message = f"Audio track count {actual} does not match required {shown}."
        fix_hint = f"Adjust the timeline to have {shown} audio track(s)."
    return SeqRuleResult(
        key="audio_track_count",
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        fix_hint=fix_hint,
    )


#: The ordered sequence-rule registry: the deterministic checks
#: :func:`check_all_sequence` runs, in report order.
SEQ_RULES = (
    check_slate_present,
    check_slate_duration,
    check_reference_audio_muted,
    check_video_track_count,
    check_audio_track_count,
)


def check_all_sequence(layout: SequenceLayout, spec: DeliverySpec) -> list[SeqRuleResult]:
    """Run every sequence rule against ``layout`` + ``spec``, in report order.

    This is the deterministic verdict the agent layer builds on. No LLM, no
    network, no OTIO — pure data in, pure results out. Missing data yields
    UNKNOWN, never an exception.
    """
    return [rule(layout, spec) for rule in SEQ_RULES]
