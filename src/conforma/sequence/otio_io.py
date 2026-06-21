"""The single OTIO boundary: read/write exported timelines, fully deterministically.

This is the **only** module in conforma that imports :mod:`opentimelineio`.
Everything downstream (extract, rules, report, fix, agent, CLI) speaks the
dependency-free :class:`~conforma.sequence.models.SequenceLayout` instead, so the
OTIO dependency stays quarantined behind one seam.

* :func:`read_timeline` dispatches by file suffix through ``otio.adapters`` and
  normalizes whatever the adapter returns (``Timeline`` |
  ``SerializableCollection`` | ``list``) into the first ``Timeline`` — FCPXML
  *library* files in particular come back as a ``SerializableCollection``.
* :func:`write_timeline` dispatches by suffix the same way.
* :func:`adapter_available` / :func:`available_adapters` report which adapters are
  importable: ``otio_json`` always ships with OTIO; ``.fcpxml`` and ``.aaf`` need
  the optional plugins (``pip install conforma[adapters]``).

A missing adapter is reported as a :class:`~conforma.sequence.errors.SequenceError`
with an actionable install hint, never a bare ``ImportError`` deep in a stack.
"""

from __future__ import annotations

import os
from typing import Any

from .errors import SequenceError

#: File suffix (lowercase, with dot) -> the ``otio.adapters`` adapter name that
#: handles it. ``otio_json`` is built in; the rest are optional plugins.
SUFFIX_ADAPTERS: dict[str, str] = {
    ".otio": "otio_json",
    ".json": "otio_json",
    ".fcpxml": "fcpx_xml",
    ".fcpxmld": "fcpx_xml",
    ".xml": "fcpx_xml",
    ".aaf": "AAF",
}

#: A human hint per adapter for the "plugin not installed" error message.
_ADAPTER_INSTALL_HINT: dict[str, str] = {
    "fcpx_xml": "otio-fcpx-xml-adapter: pip install conforma[adapters]",
    "AAF": "otio-aaf-adapter: pip install conforma[adapters]",
    "otio_json": "opentimelineio (built in)",
}


def _suffix(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _adapter_for(path: str) -> str:
    """Return the adapter name for ``path``'s suffix or raise :class:`SequenceError`."""
    suffix = _suffix(path)
    adapter = SUFFIX_ADAPTERS.get(suffix)
    if adapter is None:
        known = ", ".join(sorted(SUFFIX_ADAPTERS))
        raise SequenceError(
            f"unsupported sequence file suffix {suffix or '(none)'!r} for {path!r}. "
            f"Known suffixes: {known}."
        )
    return adapter


def adapter_available(suffix: str) -> bool:
    """Report whether the adapter for ``suffix`` is importable right now.

    ``suffix`` may be given with or without the leading dot. ``otio_json`` is
    always available (it ships with OTIO); ``fcpx_xml`` / ``AAF`` are only
    available when their optional plugin packages are installed. Returns ``False``
    for an unknown suffix.
    """
    if not suffix.startswith("."):
        suffix = "." + suffix
    adapter = SUFFIX_ADAPTERS.get(suffix.lower())
    if adapter is None:
        return False
    return _adapter_importable(adapter)


def _adapter_importable(adapter: str) -> bool:
    import opentimelineio as otio

    try:
        return adapter in set(otio.adapters.available_adapter_names())
    except Exception:  # pragma: no cover - defensive: OTIO plugin manifest error
        return False


def available_adapters() -> dict[str, bool]:
    """Return ``{adapter_name: importable}`` for every adapter conforma can use.

    A quick capability probe for the CLI / README: ``otio_json`` is always
    ``True``; ``fcpx_xml`` and ``AAF`` are ``True`` only when their plugins are
    installed.
    """
    adapters = sorted(set(SUFFIX_ADAPTERS.values()))
    return {name: _adapter_importable(name) for name in adapters}


def _normalize_to_timeline(obj: Any, *, path: str) -> Any:
    """Coerce an adapter result into the first ``otio.schema.Timeline``.

    Adapters may return a single ``Timeline``, a ``SerializableCollection`` (an
    FCPXML library with one or more timelines), or a plain ``list``. We pick the
    first contained ``Timeline`` deterministically (document order).
    """
    import opentimelineio as otio

    if isinstance(obj, otio.schema.Timeline):
        return obj

    candidates: list[Any]
    if isinstance(obj, otio.schema.SerializableCollection):
        candidates = list(obj)
    elif isinstance(obj, list):
        candidates = obj
    else:
        candidates = []

    for item in candidates:
        if isinstance(item, otio.schema.Timeline):
            return item

    raise SequenceError(
        f"no timeline found in {path!r} (adapter returned {type(obj).__name__} with no Timeline)."
    )


def read_timeline(path: str) -> Any:
    """Read an exported sequence at ``path`` into a single ``otio.schema.Timeline``.

    Dispatches by suffix (``.otio`` / ``.fcpxml`` / ``.aaf`` / ...), normalizes
    the adapter's result into the first ``Timeline``, and returns it. Raises
    :class:`~conforma.sequence.errors.SequenceError` with an install hint when the
    required adapter plugin is absent, and on any read failure (missing file,
    garbled content). The return type is the OTIO object; downstream code should
    immediately :func:`conforma.sequence.extract.extract_layout` it.
    """
    import opentimelineio as otio

    adapter = _adapter_for(path)
    if not _adapter_importable(adapter):
        hint = _ADAPTER_INSTALL_HINT.get(adapter, adapter)
        raise SequenceError(f"{_suffix(path)} requires {hint}")
    if not os.path.isfile(path):
        raise SequenceError(f"sequence file not found: {path!r}")
    try:
        obj = otio.adapters.read_from_file(path, adapter)
    except SequenceError:
        raise
    except Exception as exc:  # OTIO raises a grab-bag of exception types
        raise SequenceError(f"could not read sequence {path!r} with {adapter}: {exc}") from exc
    return _normalize_to_timeline(obj, path=path)


def write_timeline(timeline: Any, path: str) -> None:
    """Write ``timeline`` to ``path``, dispatching the adapter by suffix.

    Raises :class:`~conforma.sequence.errors.SequenceError` when the adapter is
    missing or the write fails. ``otio_json`` round-trips losslessly (track names
    + ``enabled`` flags survive); FCPXML output is best-effort and documented as
    lossy for track names.
    """
    import opentimelineio as otio

    adapter = _adapter_for(path)
    if not _adapter_importable(adapter):
        hint = _ADAPTER_INSTALL_HINT.get(adapter, adapter)
        raise SequenceError(f"{_suffix(path)} requires {hint}")
    try:
        otio.adapters.write_to_file(timeline, path, adapter)
    except Exception as exc:
        raise SequenceError(f"could not write sequence {path!r} with {adapter}: {exc}") from exc
