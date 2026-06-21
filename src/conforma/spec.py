"""Load, parse, and validate delivery specs — plus the shipped presets.

A delivery spec is YAML. :func:`parse_spec` turns an already-parsed ``dict`` into
a validated :class:`~conforma.models.Spec` (raising :class:`~conforma.errors.SpecError`
on any unknown requirement key, bad type, or missing field). :func:`load_spec`
reads a YAML file from disk and delegates to :func:`parse_spec`. The shipped
presets (Netflix-style HD ProRes, EBU/broadcast-style) live as YAML files under
``conforma/presets/`` and are resolved by name via :func:`load_preset`.

Validation is strict on purpose: a spec that references a rule conforma does not
implement is a spec authoring error, not a silent pass.
"""

from __future__ import annotations

import os
from typing import Any

import yaml

from .errors import SpecError
from .models import Requirement, Spec
from .rules import RULES

#: Directory holding the shipped preset YAML files, resolved at import time.
PRESETS_DIR: str = os.path.join(os.path.dirname(__file__), "presets")

#: Mapping of preset name -> preset YAML filename (no path). The canonical set of
#: presets conforma ships. Kept as data so the CLI can enumerate it.
PRESETS: dict[str, str] = {
    "netflix-hd": "netflix-hd.yaml",
    "ebu-broadcast": "ebu-broadcast.yaml",
}


def list_presets() -> list[str]:
    """Return the names of the shipped presets, sorted for stable output."""
    return sorted(PRESETS)


def load_preset(name: str) -> Spec:
    """Load a shipped preset by name (e.g. ``"netflix-hd"``).

    Raises :class:`~conforma.errors.SpecError` if ``name`` is not a known preset.
    The returned spec's ``source`` records the preset name.
    """
    filename = PRESETS.get(name)
    if filename is None:
        known = ", ".join(sorted(PRESETS))
        raise SpecError(f"Unknown preset {name!r}. Known presets: {known}.")
    path = os.path.join(PRESETS_DIR, filename)
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:  # pragma: no cover - shipped presets are always present
        raise SpecError(f"Could not read preset {name!r} at {path!r}: {exc}") from exc
    if not isinstance(data, dict):  # pragma: no cover - shipped presets are valid
        raise SpecError(f"Preset {name!r} did not parse to a mapping.")
    return parse_spec(data, source=name)


def load_spec(path: str) -> Spec:
    """Read and validate a delivery spec from a YAML file at ``path``.

    Raises :class:`~conforma.errors.SpecError` on a missing file, invalid YAML,
    or a spec that fails validation. The returned spec's ``source`` records
    ``path``.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise SpecError(f"Could not read spec file {path!r}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"Invalid YAML in spec file {path!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"Spec file {path!r} must parse to a top-level mapping.")
    return parse_spec(data, source=path)


def _parse_requirement(entry: Any, index: int) -> Requirement:
    if not isinstance(entry, dict):
        raise SpecError(f"requirements[{index}] must be a mapping, got {type(entry).__name__}.")
    key = entry.get("key")
    if not key or not isinstance(key, str):
        raise SpecError(f"requirements[{index}] is missing a string 'key'.")
    if key not in RULES:
        known = ", ".join(sorted(RULES))
        raise SpecError(f"requirements[{index}] has unknown key {key!r}. Known rule keys: {known}.")
    if "expected" not in entry:
        raise SpecError(f"requirement {key!r} is missing 'expected'.")
    tolerance = entry.get("tolerance")
    if tolerance is not None:
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
            raise SpecError(f"requirement {key!r} has non-numeric tolerance {tolerance!r}.")
        tolerance = float(tolerance)
    severity = entry.get("severity", "must")
    if severity not in ("must", "should"):
        raise SpecError(
            f"requirement {key!r} has invalid severity {severity!r} (expected 'must' or 'should')."
        )
    return Requirement(
        key=key,
        expected=entry["expected"],
        tolerance=tolerance,
        description=str(entry.get("description", "")),
        severity=severity,
    )


def parse_spec(data: dict[str, Any], *, source: str = "") -> Spec:
    """Validate an already-parsed spec mapping into a :class:`~conforma.models.Spec`.

    Expected shape (top level)::

        name: "Netflix HD ProRes"
        version: "1.0"
        description: "..."        # optional
        requirements:
          - key: resolution
            expected: [1920, 1080]
            description: "1080p"
          - key: frame_rate
            expected: 23.976
            tolerance: 0.01
          ...

    Every requirement ``key`` must be a rule conforma implements (see
    :data:`conforma.rules.RULES`); otherwise :class:`~conforma.errors.SpecError`
    is raised naming the offending key. ``source`` is recorded for provenance.
    """
    if not isinstance(data, dict):
        raise SpecError(f"Spec must be a mapping, got {type(data).__name__}.")
    name = data.get("name")
    if not name or not isinstance(name, str):
        raise SpecError("Spec is missing a non-empty string 'name'.")
    version = data.get("version")
    if version is None or not isinstance(version, (str, int, float)) or version == "":
        raise SpecError("Spec is missing a non-empty 'version'.")
    raw_requirements = data.get("requirements")
    if not isinstance(raw_requirements, list) or not raw_requirements:
        raise SpecError("Spec must have a non-empty 'requirements' list.")
    requirements = [_parse_requirement(entry, i) for i, entry in enumerate(raw_requirements)]
    return Spec(
        name=name,
        version=str(version),
        requirements=requirements,
        description=str(data.get("description", "")),
        source=source,
    )
