"""Studio interop correctness tests (:mod:`conforma`).

These prove the cross-cutting guarantees: probe-source agnosticism, preset
round-tripping, cross-spec discrimination, and parse-valid JSON output.
"""

from __future__ import annotations

import json
import os
from typing import Any

import yaml

from conforma.agent import ConformanceAgent
from conforma.models import CheckStatus
from conforma.probe import normalize_probe
from conforma.report import report_to_dict
from conforma.rules import check_all
from conforma.spec import PRESETS, PRESETS_DIR, list_presets, load_preset, parse_spec


def test_probe_source_agnostic_same_verdict(
    ffprobe_netflix_pass: dict[str, Any],
    mediainfo_netflix_pass: dict[str, Any],
) -> None:
    spec = load_preset("netflix-hd")
    ff_profile = normalize_probe(ffprobe_netflix_pass)
    mi_profile = normalize_probe(mediainfo_netflix_pass)

    ff_report = ConformanceAgent().check(spec, ff_profile)
    mi_report = ConformanceAgent().check(spec, mi_profile)

    assert ff_report.conformant is True
    assert mi_report.conformant is True
    # Same per-requirement verdict regardless of probe source.
    assert [(r.key, r.status) for r in ff_report.results] == [
        (r.key, r.status) for r in mi_report.results
    ]


def test_every_preset_roundtrips_to_equal_spec() -> None:
    for name in list_presets():
        loaded = load_preset(name)
        # serialize -> reparse
        serialized = loaded.as_dict()
        reparsed = parse_spec(
            {
                "name": serialized["name"],
                "version": serialized["version"],
                "description": serialized["description"],
                "requirements": serialized["requirements"],
            },
            source=name,
        )
        assert reparsed == loaded


def test_preset_yaml_files_parse_serialize_reparse() -> None:
    for name in list_presets():
        path = os.path.join(PRESETS_DIR, PRESETS[name])
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        first = parse_spec(data, source=name)
        second = parse_spec(yaml.safe_load(yaml.safe_dump(data)), source=name)
        assert first == second


def test_cross_spec_discriminates(ffprobe_ebu_pass: dict[str, Any]) -> None:
    profile = normalize_probe(ffprobe_ebu_pass)
    ebu = load_preset("ebu-broadcast")
    netflix = load_preset("netflix-hd")

    # Conforms to EBU.
    ebu_report = ConformanceAgent().check(ebu, profile)
    assert ebu_report.conformant is True

    # Fails Netflix on the discriminating dimensions.
    netflix_results = {r.key: r for r in check_all(netflix.requirements, profile)}
    for key in ("frame_rate", "scan_type", "video_codec", "bit_depth"):
        assert netflix_results[key].status == CheckStatus.FAIL, key
    netflix_report = ConformanceAgent().check(netflix, profile)
    assert netflix_report.conformant is False


def test_report_to_dict_roundtrips_through_json(ffprobe_netflix_fail: dict[str, Any]) -> None:
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_fail)
    report = ConformanceAgent().check(spec, profile)
    d = report_to_dict(report)
    assert json.loads(json.dumps(d)) == d
