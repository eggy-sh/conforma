"""Unit tests for the core data model (:mod:`conforma.models`)."""

from __future__ import annotations

import json

from conforma.models import (
    AudioProfile,
    CheckStatus,
    ConformanceReport,
    MediaProfile,
    Requirement,
    RuleResult,
    Spec,
    VideoProfile,
)


def _result(key: str, status: CheckStatus, severity: str = "must") -> RuleResult:
    return RuleResult(
        key=key,
        status=status,
        expected="x",
        actual="y",
        message=f"{key} {status}",
        severity=severity,
    )


def test_checkstatus_serializes_to_plain_strings() -> None:
    assert str(CheckStatus.PASS) == "pass"
    assert str(CheckStatus.FAIL) == "fail"
    assert str(CheckStatus.UNKNOWN) == "unknown"
    # StrEnum members compare equal to their string value.
    assert CheckStatus.PASS == "pass"
    assert json.dumps({"s": CheckStatus.FAIL}) == '{"s": "fail"}'


def test_rule_result_passed_only_for_pass() -> None:
    assert _result("a", CheckStatus.PASS).passed is True
    assert _result("a", CheckStatus.FAIL).passed is False
    assert _result("a", CheckStatus.UNKNOWN).passed is False


def test_requirement_as_dict_json_safe() -> None:
    req = Requirement(
        key="frame_rate",
        expected=23.976,
        tolerance=0.01,
        description="23.976 fps",
        severity="must",
    )
    d = req.as_dict()
    assert d == {
        "key": "frame_rate",
        "expected": 23.976,
        "tolerance": 0.01,
        "description": "23.976 fps",
        "severity": "must",
    }
    json.dumps(d)  # must not raise


def test_spec_as_dict_includes_requirements() -> None:
    spec = Spec(
        name="N",
        version="1.0",
        requirements=[Requirement(key="container", expected="mov")],
        description="d",
        source="src",
    )
    d = spec.as_dict()
    assert d["name"] == "N"
    assert d["version"] == "1.0"
    assert d["source"] == "src"
    assert d["requirements"][0]["key"] == "container"
    json.dumps(d)


def test_video_and_audio_profile_as_dict() -> None:
    video = VideoProfile(codec="prores", width=1920, height=1080, frame_rate=23.976, bit_depth=10)
    audio = AudioProfile(codec="pcm", channels=2, sample_rate=48000, bit_depth=24, language="eng")
    vd = video.as_dict()
    ad = audio.as_dict()
    assert vd["codec"] == "prores"
    assert vd["width"] == 1920
    assert ad["channels"] == 2
    assert ad["language"] == "eng"
    json.dumps(vd)
    json.dumps(ad)


def test_media_profile_as_dict_excludes_raw() -> None:
    profile = MediaProfile(
        container="mov",
        video=VideoProfile(codec="prores"),
        audio=[AudioProfile(codec="pcm")],
        duration_seconds=10.0,
        source="ffprobe",
        raw={"secret": "should-not-serialize"},
    )
    d = profile.as_dict()
    assert "raw" not in d
    assert d["container"] == "mov"
    assert d["video"]["codec"] == "prores"
    assert d["audio"][0]["codec"] == "pcm"
    json.dumps(d)


def test_media_profile_as_dict_handles_no_video() -> None:
    profile = MediaProfile(container="mxf", video=None, audio=[])
    d = profile.as_dict()
    assert d["video"] is None
    assert d["audio"] == []


def test_rule_result_as_dict_status_is_string() -> None:
    result = _result("container", CheckStatus.FAIL)
    d = result.as_dict()
    assert d["status"] == "fail"
    assert isinstance(d["status"], str)
    json.dumps(d)


def test_report_conformant_false_when_must_fails() -> None:
    report = ConformanceReport(
        spec_name="N",
        spec_version="1.0",
        media_source="src",
        results=[
            _result("a", CheckStatus.PASS),
            _result("b", CheckStatus.FAIL, severity="must"),
        ],
    )
    assert report.conformant is False


def test_report_conformant_true_when_only_should_fails() -> None:
    report = ConformanceReport(
        spec_name="N",
        spec_version="1.0",
        media_source="src",
        results=[
            _result("a", CheckStatus.PASS),
            _result("b", CheckStatus.FAIL, severity="should"),
        ],
    )
    assert report.conformant is True


def test_report_conformant_true_with_unknowns() -> None:
    report = ConformanceReport(
        spec_name="N",
        spec_version="1.0",
        media_source="src",
        results=[
            _result("a", CheckStatus.PASS),
            _result("b", CheckStatus.UNKNOWN),
        ],
    )
    assert report.conformant is True


def test_report_failures_in_order() -> None:
    report = ConformanceReport(
        spec_name="N",
        spec_version="1.0",
        media_source="src",
        results=[
            _result("a", CheckStatus.FAIL),
            _result("b", CheckStatus.PASS),
            _result("c", CheckStatus.FAIL),
        ],
    )
    assert [r.key for r in report.failures] == ["a", "c"]


def test_report_counts_tally() -> None:
    report = ConformanceReport(
        spec_name="N",
        spec_version="1.0",
        media_source="src",
        results=[
            _result("a", CheckStatus.PASS),
            _result("b", CheckStatus.PASS),
            _result("c", CheckStatus.FAIL),
            _result("d", CheckStatus.UNKNOWN),
        ],
    )
    assert report.counts() == {"pass": 2, "fail": 1, "unknown": 1}


def test_report_as_dict_json_safe() -> None:
    report = ConformanceReport(
        spec_name="N",
        spec_version="1.0",
        media_source="src",
        results=[_result("a", CheckStatus.PASS)],
        llm_summary="all good",
    )
    d = report.as_dict()
    assert d["spec_name"] == "N"
    assert d["conformant"] is True
    assert d["counts"]["pass"] == 1
    assert d["llm_summary"] == "all good"
    assert d["results"][0]["key"] == "a"
    json.dumps(d)
