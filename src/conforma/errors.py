"""The conforma exception hierarchy.

All errors raised by conforma's own code derive from :class:`ConformaError`, so
callers (and the CLI) can distinguish a conforma-level failure (bad spec, bad
probe JSON) from an unexpected bug.
"""

from __future__ import annotations


class ConformaError(Exception):
    """Base class for every error conforma raises deliberately."""


class SpecError(ConformaError):
    """Raised when a delivery spec is missing, malformed, or fails validation.

    Carries a human-readable ``message`` describing exactly what is wrong (e.g.
    an unknown requirement key, a non-numeric tolerance, an unknown preset name).
    """


class ProbeError(ConformaError):
    """Raised when probe input cannot be read or normalized.

    Covers: file-not-found, invalid JSON, an unrecognized probe shape (neither
    ffprobe nor MediaInfo), or a failed/absent ``ffprobe`` invocation when one was
    explicitly requested.
    """
