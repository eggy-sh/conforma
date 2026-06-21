"""Unit tests for the sequence delivery-spec loader (:mod:`conforma.sequence.delivery_spec`)."""

from __future__ import annotations

import json

import pytest

from conforma.sequence.delivery_spec import (
    SEQ_PRESETS,
    DeliverySpec,
    list_seq_presets,
    load_delivery_spec,
    load_seq_preset,
    parse_delivery_spec,
)
from conforma.sequence.errors import SequenceSpecError


def _valid_spec_dict() -> dict:
    return {
        "name": "Netflix IMF",
        "version": "1.0",
        "description": "test",
        "sequence": {
            "slate": {"required": True, "duration_seconds": 5, "tolerance_seconds": 0.5},
            "expected_video_tracks": 1,
            "expected_audio_tracks": [4, 8],
            "reference_audio_must_be_muted": True,
            "reference_role_keywords": ["wip", "house"],
        },
    }


def test_load_seq_preset_netflix_imf_validates() -> None:
    spec = load_seq_preset("netflix-imf")
    assert isinstance(spec, DeliverySpec)
    assert spec.name == "Netflix IMF Editorial"
    assert spec.slate_required is True
    assert spec.slate_duration_seconds == 5
    assert spec.slate_tolerance_seconds == 0.5
    assert spec.expected_video_tracks == 1
    assert spec.expected_audio_tracks == [4, 8]
    assert spec.reference_audio_must_be_muted is True
    assert "wip" in spec.reference_role_keywords
    assert spec.source == "netflix-imf"


def test_list_seq_presets_sorted() -> None:
    presets = list_seq_presets()
    assert "netflix-imf" in presets
    assert presets == sorted(presets)
    assert set(presets) == set(SEQ_PRESETS)


def test_load_seq_preset_unknown_raises() -> None:
    with pytest.raises(SequenceSpecError, match="Unknown sequence preset"):
        load_seq_preset("nope")


def test_parse_delivery_spec_roundtrips_fields() -> None:
    spec = parse_delivery_spec(_valid_spec_dict(), source="inline")
    assert spec.name == "Netflix IMF"
    assert spec.version == "1.0"
    assert spec.expected_audio_tracks == [4, 8]
    assert spec.reference_role_keywords == ("wip", "house")
    assert spec.source == "inline"


def test_parse_delivery_spec_as_dict_json_safe() -> None:
    spec = parse_delivery_spec(_valid_spec_dict())
    payload = json.dumps(spec.as_dict())
    restored = json.loads(payload)
    assert restored["sequence"]["slate"]["duration_seconds"] == 5
    assert restored["sequence"]["expected_audio_tracks"] == [4, 8]


def test_parse_delivery_spec_missing_name_raises() -> None:
    data = _valid_spec_dict()
    del data["name"]
    with pytest.raises(SequenceSpecError, match="name"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_missing_version_raises() -> None:
    data = _valid_spec_dict()
    del data["version"]
    with pytest.raises(SequenceSpecError, match="version"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_missing_sequence_block_raises() -> None:
    with pytest.raises(SequenceSpecError, match="sequence"):
        parse_delivery_spec({"name": "x", "version": "1"})


def test_parse_delivery_spec_unknown_sequence_key_raises() -> None:
    data = _valid_spec_dict()
    data["sequence"]["bogus_key"] = 1
    with pytest.raises(SequenceSpecError, match="unknown keys"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_unknown_slate_key_raises() -> None:
    data = _valid_spec_dict()
    data["sequence"]["slate"]["bogus"] = 1
    with pytest.raises(SequenceSpecError, match="unknown keys"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_non_numeric_slate_duration_raises() -> None:
    data = _valid_spec_dict()
    data["sequence"]["slate"]["duration_seconds"] = "five"
    with pytest.raises(SequenceSpecError, match="duration_seconds"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_bool_slate_duration_rejected() -> None:
    data = _valid_spec_dict()
    data["sequence"]["slate"]["duration_seconds"] = True
    with pytest.raises(SequenceSpecError, match="duration_seconds"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_bad_track_count_type_raises() -> None:
    data = _valid_spec_dict()
    data["sequence"]["expected_video_tracks"] = "one"
    with pytest.raises(SequenceSpecError, match="expected_video_tracks"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_bool_track_count_rejected() -> None:
    data = _valid_spec_dict()
    data["sequence"]["expected_video_tracks"] = True
    with pytest.raises(SequenceSpecError, match="expected_video_tracks"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_track_count_list_entries_must_be_ints() -> None:
    data = _valid_spec_dict()
    data["sequence"]["expected_audio_tracks"] = [4, "8"]
    with pytest.raises(SequenceSpecError, match="ints"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_empty_track_count_list_rejected() -> None:
    data = _valid_spec_dict()
    data["sequence"]["expected_audio_tracks"] = []
    with pytest.raises(SequenceSpecError, match="empty"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_non_bool_ref_muted_raises() -> None:
    data = _valid_spec_dict()
    data["sequence"]["reference_audio_must_be_muted"] = "yes"
    with pytest.raises(SequenceSpecError, match="reference_audio_must_be_muted"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_bad_ref_keywords_raises() -> None:
    data = _valid_spec_dict()
    data["sequence"]["reference_role_keywords"] = "wip"
    with pytest.raises(SequenceSpecError, match="reference_role_keywords"):
        parse_delivery_spec(data)


def test_parse_delivery_spec_optional_fields_default_to_none() -> None:
    spec = parse_delivery_spec({"name": "x", "version": "1", "sequence": {}})
    assert spec.slate_required is None
    assert spec.slate_duration_seconds is None
    assert spec.expected_video_tracks is None
    assert spec.expected_audio_tracks is None
    assert spec.reference_audio_must_be_muted is None
    assert spec.reference_role_keywords == ()


def test_load_delivery_spec_from_yaml_file(tmp_path) -> None:
    yaml_text = (
        "name: My Spec\n"
        "version: 2\n"
        "sequence:\n"
        "  slate:\n"
        "    required: true\n"
        "    duration_seconds: 3\n"
        "  expected_video_tracks: 1\n"
    )
    path = tmp_path / "spec.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    spec = load_delivery_spec(str(path))
    assert spec.name == "My Spec"
    assert spec.version == "2"
    assert spec.slate_duration_seconds == 3
    assert spec.source == str(path)


def test_load_delivery_spec_missing_file_raises(tmp_path) -> None:
    with pytest.raises(SequenceSpecError, match="Could not read"):
        load_delivery_spec(str(tmp_path / "nope.yaml"))


def test_load_delivery_spec_non_mapping_raises(tmp_path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(SequenceSpecError, match="top-level mapping"):
        load_delivery_spec(str(path))


def test_load_delivery_spec_invalid_yaml_raises(tmp_path) -> None:
    path = tmp_path / "spec.yaml"
    # Unbalanced brackets -> a YAML parse error, wrapped as SequenceSpecError.
    path.write_text("name: x\nversion: 1\nsequence: [unclosed\n", encoding="utf-8")
    with pytest.raises(SequenceSpecError, match="Invalid YAML"):
        load_delivery_spec(str(path))


def test_parse_delivery_spec_non_mapping_slate_raises() -> None:
    data = _valid_spec_dict()
    data["sequence"]["slate"] = ["not", "a", "mapping"]
    with pytest.raises(SequenceSpecError, match="sequence.slate must be a mapping"):
        parse_delivery_spec(data)
