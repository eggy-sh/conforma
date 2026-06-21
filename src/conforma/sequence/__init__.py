"""Sequence-level conformance — judging an exported *timeline*, not a file.

Where the top-level :mod:`conforma` package checks a single rendered media file
against a delivery spec (resolution, codec, audio config…), this subpackage
checks the **editorial sequence** an NLE exported — a Final Cut ``.fcpxml``, an
Avid ``.aaf``, or a lossless OpenTimelineIO ``.otio`` — against a *sequence*-level
delivery spec: is there a 5-second slate, is the reference/scratch audio track
muted, does the track layout match the IMF/Netflix-style expectation?

The whole verdict is **deterministic** and dependency-light:

* :mod:`~conforma.sequence.otio_io` is the *only* module that imports
  ``opentimelineio``; it reads/writes a single :class:`otio.schema.Timeline`.
* :mod:`~conforma.sequence.extract` projects that Timeline into a small,
  JSON-serializable :class:`~conforma.sequence.models.SequenceLayout` (timecode
  arithmetic + literal keyword role matching; no model).
* :mod:`~conforma.sequence.delivery_spec` parses/validates the sequence spec.
* :mod:`~conforma.sequence.rules` runs fixed-threshold checks (slate duration,
  reference-muted, track counts) producing ordered
  :class:`~conforma.sequence.models.SeqRuleResult`\\ s — no LLM, missing data
  yields ``UNKNOWN`` rather than an exception.
* :mod:`~conforma.sequence.report` renders JSON / Rich / Markdown projections.
* :mod:`~conforma.sequence.fix` emits a corrected Timeline (mute the ref track,
  flag the slate) without mutating the source.

The optional :mod:`~conforma.sequence.agent` is the *thin* replykit layer: it
only (1) classifies audio tracks the deterministic extractor left
``role='unknown'`` and (2) writes a human-readable audit narrative. With no
model it is a pure pass-through to the deterministic rules, which is the
hermetic default the tests and the CLI's offline mode use.
"""

from __future__ import annotations

from .errors import SequenceError, SequenceSpecError

__all__ = [
    "SequenceError",
    "SequenceSpecError",
]
