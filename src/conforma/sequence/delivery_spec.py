"""Load, parse, and validate a sequence-level delivery spec — plus its presets.

Mirrors :mod:`conforma.spec` exactly for the sequence domain. A delivery spec is
YAML with a top-level ``name`` / ``version`` and a ``sequence`` block of
checkable fields. :func:`parse_delivery_spec` validates an already-parsed dict
into a frozen :class:`DeliverySpec` (raising
:class:`~conforma.sequence.errors.SequenceSpecError` on any unknown key or bad
type); :func:`load_delivery_spec` reads a YAML file and delegates.
:func:`load_seq_preset` / :func:`list_seq_presets` resolve the shipped
``netflix-imf`` preset under ``conforma/sequence/presets/``.

Validation is strict on purpose: a spec field conforma does not check is a spec
authoring error, not a silent pass.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from .errors import SequenceSpecError

#: Directory holding the shipped sequence preset YAML files.
PRESETS_DIR: str = os.path.join(os.path.dirname(__file__), "presets")

#: Mapping of preset name -> preset YAML filename. Kept as data so the CLI can
#: enumerate it (mirrors :data:`conforma.spec.PRESETS`).
SEQ_PRESETS: dict[str, str] = {
    "netflix-imf": "netflix-imf.yaml",
}

#: The set of keys allowed inside the ``sequence`` block. Anything else is a
#: validation error (strict, like the media spec validator).
_ALLOWED_SEQUENCE_KEYS = {
    "slate",
    "expected_video_tracks",
    "expected_audio_tracks",
    "reference_audio_must_be_muted",
    "reference_role_keywords",
}
_ALLOWED_SLATE_KEYS = {"required", "duration_seconds", "tolerance_seconds"}


@dataclass(frozen=True)
class DeliverySpec:
    """A parsed, validated sequence-level delivery spec.

    Every field is optional at the rule layer (a missing field yields UNKNOWN,
    never a crash); presence here just declares what to check. Built only via
    :func:`parse_delivery_spec` / :func:`load_delivery_spec`, which guarantee
    types and reject unknown keys.
    """

    name: str
    version: str
    slate_required: bool | None = None
    slate_duration_seconds: float | None = None
    slate_tolerance_seconds: float = 0.0
    expected_video_tracks: int | list[int] | None = None
    expected_audio_tracks: int | list[int] | None = None
    reference_audio_must_be_muted: bool | None = None
    reference_role_keywords: tuple[str, ...] = ()
    description: str = ""
    source: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable view of this spec."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "source": self.source,
            "sequence": {
                "slate": {
                    "required": self.slate_required,
                    "duration_seconds": self.slate_duration_seconds,
                    "tolerance_seconds": self.slate_tolerance_seconds,
                },
                "expected_video_tracks": self.expected_video_tracks,
                "expected_audio_tracks": self.expected_audio_tracks,
                "reference_audio_must_be_muted": self.reference_audio_must_be_muted,
                "reference_role_keywords": list(self.reference_role_keywords),
            },
        }


def list_seq_presets() -> list[str]:
    """Return the names of the shipped sequence presets, sorted for stable output."""
    return sorted(SEQ_PRESETS)


def load_seq_preset(name: str) -> DeliverySpec:
    """Load a shipped sequence preset by name (e.g. ``"netflix-imf"``).

    Raises :class:`~conforma.sequence.errors.SequenceSpecError` if ``name`` is not
    a known preset. The returned spec's ``source`` records the preset name.
    """
    filename = SEQ_PRESETS.get(name)
    if filename is None:
        known = ", ".join(sorted(SEQ_PRESETS))
        raise SequenceSpecError(f"Unknown sequence preset {name!r}. Known presets: {known}.")
    path = os.path.join(PRESETS_DIR, filename)
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:  # pragma: no cover - shipped presets are always present
        raise SequenceSpecError(f"Could not read preset {name!r} at {path!r}: {exc}") from exc
    if not isinstance(data, dict):  # pragma: no cover - shipped presets are valid
        raise SequenceSpecError(f"Preset {name!r} did not parse to a mapping.")
    return parse_delivery_spec(data, source=name)


def load_delivery_spec(path: str) -> DeliverySpec:
    """Read and validate a sequence delivery spec from a YAML file at ``path``.

    Raises :class:`~conforma.sequence.errors.SequenceSpecError` on a missing file,
    invalid YAML, or a spec that fails validation. ``source`` records ``path``.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise SequenceSpecError(f"Could not read spec file {path!r}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SequenceSpecError(f"Invalid YAML in spec file {path!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise SequenceSpecError(f"Spec file {path!r} must parse to a top-level mapping.")
    return parse_delivery_spec(data, source=path)


def _as_int_or_int_list(value: Any, field_name: str) -> int | list[int]:
    if isinstance(value, bool):
        raise SequenceSpecError(f"{field_name} must be an int or list of ints, got a bool.")
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        out: list[int] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int):
                raise SequenceSpecError(f"{field_name} list entries must be ints, got {item!r}.")
            out.append(item)
        if not out:
            raise SequenceSpecError(f"{field_name} list must not be empty.")
        return out
    raise SequenceSpecError(
        f"{field_name} must be an int or list of ints, got {type(value).__name__}."
    )


def _require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise SequenceSpecError(f"{field_name} must be a bool, got {type(value).__name__}.")
    return value


def _require_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SequenceSpecError(f"{field_name} must be a number, got {type(value).__name__}.")
    return float(value)


def _parse_slate(block: Any) -> dict[str, Any]:
    if not isinstance(block, dict):
        raise SequenceSpecError(f"sequence.slate must be a mapping, got {type(block).__name__}.")
    unknown = set(block) - _ALLOWED_SLATE_KEYS
    if unknown:
        raise SequenceSpecError(
            f"sequence.slate has unknown keys: {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_SLATE_KEYS))}."
        )
    out: dict[str, Any] = {}
    if "required" in block:
        out["required"] = _require_bool(block["required"], "sequence.slate.required")
    if "duration_seconds" in block:
        out["duration_seconds"] = _require_number(
            block["duration_seconds"], "sequence.slate.duration_seconds"
        )
    if "tolerance_seconds" in block:
        out["tolerance_seconds"] = _require_number(
            block["tolerance_seconds"], "sequence.slate.tolerance_seconds"
        )
    return out


def parse_delivery_spec(data: dict[str, Any], *, source: str = "") -> DeliverySpec:
    """Validate an already-parsed mapping into a :class:`DeliverySpec`.

    Expected shape::

        name: "Netflix IMF"
        version: "1.0"
        sequence:
          slate:
            required: true
            duration_seconds: 5
            tolerance_seconds: 0.5
          expected_video_tracks: 1
          expected_audio_tracks: [4, 8]
          reference_audio_must_be_muted: true
          reference_role_keywords: ["wip", "house"]   # optional, extends keywords

    Raises :class:`~conforma.sequence.errors.SequenceSpecError` on unknown keys or
    bad types. ``source`` is recorded for provenance.
    """
    if not isinstance(data, dict):
        raise SequenceSpecError(f"Spec must be a mapping, got {type(data).__name__}.")
    name = data.get("name")
    if not name or not isinstance(name, str):
        raise SequenceSpecError("Spec is missing a non-empty string 'name'.")
    version = data.get("version")
    if version is None or not isinstance(version, (str, int, float)) or version == "":
        raise SequenceSpecError("Spec is missing a non-empty 'version'.")

    sequence = data.get("sequence")
    if not isinstance(sequence, dict):
        raise SequenceSpecError("Spec must have a 'sequence' mapping block.")
    unknown = set(sequence) - _ALLOWED_SEQUENCE_KEYS
    if unknown:
        raise SequenceSpecError(
            f"sequence block has unknown keys: {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_SEQUENCE_KEYS))}."
        )

    slate = _parse_slate(sequence["slate"]) if "slate" in sequence else {}

    expected_video = (
        _as_int_or_int_list(sequence["expected_video_tracks"], "sequence.expected_video_tracks")
        if "expected_video_tracks" in sequence
        else None
    )
    expected_audio = (
        _as_int_or_int_list(sequence["expected_audio_tracks"], "sequence.expected_audio_tracks")
        if "expected_audio_tracks" in sequence
        else None
    )
    ref_muted = (
        _require_bool(
            sequence["reference_audio_must_be_muted"],
            "sequence.reference_audio_must_be_muted",
        )
        if "reference_audio_must_be_muted" in sequence
        else None
    )

    ref_keywords: tuple[str, ...] = ()
    if "reference_role_keywords" in sequence:
        raw_kw = sequence["reference_role_keywords"]
        if not isinstance(raw_kw, list) or not all(isinstance(k, str) for k in raw_kw):
            raise SequenceSpecError("sequence.reference_role_keywords must be a list of strings.")
        ref_keywords = tuple(k.strip().lower() for k in raw_kw if k.strip())

    return DeliverySpec(
        name=name,
        version=str(version),
        slate_required=slate.get("required"),
        slate_duration_seconds=slate.get("duration_seconds"),
        slate_tolerance_seconds=float(slate.get("tolerance_seconds", 0.0)),
        expected_video_tracks=expected_video,
        expected_audio_tracks=expected_audio,
        reference_audio_must_be_muted=ref_muted,
        reference_role_keywords=ref_keywords,
        description=str(data.get("description", "")),
        source=source,
        raw=data,
    )
