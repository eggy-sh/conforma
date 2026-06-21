"""Sequence-domain exceptions, rooted in conforma's existing hierarchy.

Both derive from :class:`conforma.errors.ConformaError` so the CLI's single
``except conforma.ConformaError`` handler maps a bad timeline / bad delivery spec
to a clean exit code 2 — exactly like the v0.1 ``SpecError`` / ``ProbeError`` do
for the media path.
"""

from __future__ import annotations

from ..errors import ConformaError


class SequenceError(ConformaError):
    """Raised when a sequence (exported timeline) cannot be read or normalized.

    Covers: a missing OTIO adapter plugin (with an actionable
    ``pip install conforma[adapters]`` hint), an unreadable/garbled timeline
    file, or a file whose suffix has no known adapter.
    """


class SequenceSpecError(ConformaError):
    """Raised when a sequence-level delivery spec fails validation.

    Carries a human-readable message naming the offending field (an unknown key,
    a bad type, an unknown preset name) — the sequence analogue of
    :class:`conforma.errors.SpecError`.
    """
