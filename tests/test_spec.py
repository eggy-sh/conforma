"""Unit tests for spec loading/parsing/validation (:mod:`conforma.spec`)."""

from __future__ import annotations

import pytest
import yaml

from conforma.errors import SpecError
from conforma.spec import (
    PRESETS,
    PRESETS_DIR,
    list_presets,
    load_preset,
    load_spec,
    parse_spec,
)


def test_list_presets_sorted() -> None:
    assert list_presets() == ["ebu-broadcast", "netflix-hd"]


@pytest.mark.parametrize("name", ["netflix-hd", "ebu-broadcast"])
def test_load_preset_parses_nine_requirements(name: str) -> None:
    spec = load_preset(name)
    assert len(spec.requirements) == 9
    assert spec.source == name
    assert spec.name
    assert spec.version


def test_load_preset_unknown_raises() -> None:
    with pytest.raises(SpecError, match="Unknown preset"):
        load_preset("does-not-exist")


def test_parse_spec_unknown_requirement_key_raises() -> None:
    data = {
        "name": "Bad",
        "version": "1.0",
        "requirements": [{"key": "made_up_thing", "expected": 1}],
    }
    with pytest.raises(SpecError, match="unknown key"):
        parse_spec(data)


def test_parse_spec_missing_name_raises() -> None:
    data = {"version": "1.0", "requirements": [{"key": "container", "expected": "mov"}]}
    with pytest.raises(SpecError, match="name"):
        parse_spec(data)


def test_parse_spec_missing_version_raises() -> None:
    data = {"name": "X", "requirements": [{"key": "container", "expected": "mov"}]}
    with pytest.raises(SpecError, match="version"):
        parse_spec(data)


def test_parse_spec_non_numeric_tolerance_raises() -> None:
    data = {
        "name": "X",
        "version": "1.0",
        "requirements": [{"key": "frame_rate", "expected": 24.0, "tolerance": "loose"}],
    }
    with pytest.raises(SpecError, match="tolerance"):
        parse_spec(data)


def test_parse_spec_missing_expected_raises() -> None:
    data = {"name": "X", "version": "1.0", "requirements": [{"key": "container"}]}
    with pytest.raises(SpecError, match="expected"):
        parse_spec(data)


def test_parse_spec_empty_requirements_raises() -> None:
    data = {"name": "X", "version": "1.0", "requirements": []}
    with pytest.raises(SpecError, match="requirements"):
        parse_spec(data)


def test_parse_spec_invalid_severity_raises() -> None:
    data = {
        "name": "X",
        "version": "1.0",
        "requirements": [{"key": "container", "expected": "mov", "severity": "maybe"}],
    }
    with pytest.raises(SpecError, match="severity"):
        parse_spec(data)


def test_parse_spec_records_source_and_severity() -> None:
    data = {
        "name": "X",
        "version": 2,
        "requirements": [
            {"key": "container", "expected": "mov", "severity": "should", "description": "d"}
        ],
    }
    spec = parse_spec(data, source="inline")
    assert spec.source == "inline"
    assert spec.version == "2"
    assert spec.requirements[0].severity == "should"
    assert spec.requirements[0].description == "d"


def test_load_spec_missing_file_raises() -> None:
    with pytest.raises(SpecError):
        load_spec("/no/such/spec.yaml")


def test_load_spec_invalid_yaml_raises(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: [unclosed\n", encoding="utf-8")
    with pytest.raises(SpecError):
        load_spec(str(bad))


def test_load_spec_non_mapping_raises(tmp_path) -> None:
    bad = tmp_path / "list.yaml"
    bad.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(SpecError, match="mapping"):
        load_spec(str(bad))


def test_load_spec_valid_roundtrip(tmp_path) -> None:
    good = tmp_path / "good.yaml"
    good.write_text(
        "name: My Spec\nversion: '1.0'\nrequirements:\n  - key: container\n    expected: mov\n",
        encoding="utf-8",
    )
    spec = load_spec(str(good))
    assert spec.name == "My Spec"
    assert spec.source == str(good)
    assert spec.requirements[0].key == "container"


@pytest.mark.parametrize("name", ["netflix-hd", "ebu-broadcast"])
def test_preset_roundtrip_equals_load_preset(name: str) -> None:
    import os

    path = os.path.join(PRESETS_DIR, PRESETS[name])
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    reparsed = parse_spec(data, source=name)
    loaded = load_preset(name)
    assert reparsed.name == loaded.name
    assert reparsed.version == loaded.version
    assert [r.key for r in reparsed.requirements] == [r.key for r in loaded.requirements]
