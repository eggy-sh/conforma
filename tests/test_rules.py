"""Unit tests for the deterministic rules (:mod:`conforma.rules`)."""

from __future__ import annotations

from typing import Any

import pytest

from conforma.models import (
    AudioProfile,
    CheckStatus,
    MediaProfile,
    Requirement,
    VideoProfile,
)
from conforma.probe import normalize_probe
from conforma.rules import (
    RULES,
    check_all,
    check_container,
    check_frame_rate,
    check_requirement,
    check_video_codec,
)
from conforma.spec import load_preset


def _profile(
    video: VideoProfile | None = None,
    audio: list[AudioProfile] | None = None,
    container: str | None = None,
) -> MediaProfile:
    return MediaProfile(container=container, video=video, audio=audio or [])


def test_every_rule_key_has_a_rule() -> None:
    expected_keys = {
        "resolution",
        "frame_rate",
        "video_codec",
        "bit_depth",
        "scan_type",
        "audio_codec",
        "audio_channels",
        "audio_sample_rate",
        "container",
    }
    assert set(RULES) == expected_keys
    for key, rule in RULES.items():
        assert rule.key == key
        assert callable(rule.check)
        assert rule.label


def test_check_all_netflix_pass_all_pass(ffprobe_netflix_pass: dict[str, Any]) -> None:
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_pass)
    results = check_all(spec.requirements, profile)
    assert all(r.status == CheckStatus.PASS for r in results)


def test_check_all_netflix_fail_expected_failures(ffprobe_netflix_fail: dict[str, Any]) -> None:
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_netflix_fail)
    by_key = {r.key: r for r in check_all(spec.requirements, profile)}
    for key in (
        "resolution",
        "frame_rate",
        "video_codec",
        "bit_depth",
        "audio_codec",
        "audio_sample_rate",
    ):
        assert by_key[key].status == CheckStatus.FAIL, key
    # container is mov,mp4,... which matches spec 'mov'; channels 2 matches.
    assert by_key["container"].status == CheckStatus.PASS
    assert by_key["audio_channels"].status == CheckStatus.PASS
    assert by_key["scan_type"].status == CheckStatus.PASS


def test_check_all_sparse_unknowns(ffprobe_sparse: dict[str, Any]) -> None:
    spec = load_preset("netflix-hd")
    profile = normalize_probe(ffprobe_sparse)
    by_key = {r.key: r for r in check_all(spec.requirements, profile)}
    assert by_key["bit_depth"].status == CheckStatus.UNKNOWN
    assert by_key["scan_type"].status == CheckStatus.UNKNOWN
    assert by_key["audio_codec"].status == CheckStatus.UNKNOWN
    assert by_key["audio_channels"].status == CheckStatus.UNKNOWN
    assert by_key["audio_sample_rate"].status == CheckStatus.UNKNOWN
    # The fields the probe did carry still resolve.
    assert by_key["resolution"].status == CheckStatus.PASS
    assert by_key["video_codec"].status == CheckStatus.PASS
    assert by_key["frame_rate"].status == CheckStatus.PASS


def test_video_codec_alias_aware() -> None:
    req = Requirement(key="video_codec", expected="prores")
    profile = _profile(video=VideoProfile(codec="prores_ks"))
    assert check_video_codec(req, profile).status == CheckStatus.PASS


def test_video_codec_case_insensitive() -> None:
    req = Requirement(key="video_codec", expected="ProRes")
    profile = _profile(video=VideoProfile(codec="PRORES"))
    assert check_video_codec(req, profile).status == CheckStatus.PASS


def test_container_comma_joined_format_name() -> None:
    req = Requirement(key="container", expected="mov")
    profile = _profile(container="mov,mp4,m4a,3gp,3g2,mj2")
    assert check_container(req, profile).status == CheckStatus.PASS


def test_container_fail_when_absent_from_family() -> None:
    req = Requirement(key="container", expected="mxf")
    profile = _profile(container="mov,mp4,m4a")
    assert check_container(req, profile).status == CheckStatus.FAIL


def test_frame_rate_tolerance_pass() -> None:
    # 23.976 within default/explicit tolerance of 24000/1001.
    req = Requirement(key="frame_rate", expected=23.976, tolerance=0.01)
    profile = _profile(video=VideoProfile(frame_rate=24000 / 1001))
    assert check_frame_rate(req, profile).status == CheckStatus.PASS


def test_frame_rate_tolerance_fail() -> None:
    req = Requirement(key="frame_rate", expected=23.976, tolerance=0.01)
    profile = _profile(video=VideoProfile(frame_rate=25.0))
    assert check_frame_rate(req, profile).status == CheckStatus.FAIL


def test_frame_rate_list_of_accepted_rates() -> None:
    req = Requirement(key="frame_rate", expected=[23.976, 24.0, 25.0], tolerance=0.01)
    profile = _profile(video=VideoProfile(frame_rate=25.0))
    assert check_frame_rate(req, profile).status == CheckStatus.PASS


def test_frame_rate_unknown_when_missing() -> None:
    req = Requirement(key="frame_rate", expected=24.0)
    profile = _profile(video=VideoProfile(frame_rate=None))
    assert check_frame_rate(req, profile).status == CheckStatus.UNKNOWN


def test_check_requirement_dispatches() -> None:
    req = Requirement(key="container", expected="mov")
    profile = _profile(container="mov")
    assert check_requirement(req, profile).status == CheckStatus.PASS


@pytest.mark.parametrize(
    "fixture_name",
    [
        "ffprobe_netflix_pass",
        "ffprobe_netflix_fail",
        "ffprobe_ebu_pass",
        "ffprobe_sparse",
        "mediainfo_netflix_pass",
    ],
)
def test_rules_never_raise_on_any_fixture(load_fixture: Any, fixture_name: str) -> None:
    profile = normalize_probe(load_fixture(fixture_name))
    for spec_name in ("netflix-hd", "ebu-broadcast"):
        spec = load_preset(spec_name)
        # Must not raise on any requirement.
        results = check_all(spec.requirements, profile)
        assert len(results) == len(spec.requirements)


def test_audio_codec_pass_when_any_stream_matches() -> None:
    req = Requirement(key="audio_codec", expected="pcm")
    profile = _profile(audio=[AudioProfile(codec="aac"), AudioProfile(codec="pcm_s24le")])
    from conforma.rules import check_audio_codec

    assert check_audio_codec(req, profile).status == CheckStatus.PASS


def test_audio_channels_list_expected() -> None:
    from conforma.rules import check_audio_channels

    req = Requirement(key="audio_channels", expected=[2, 6])
    profile = _profile(audio=[AudioProfile(channels=6)])
    assert check_audio_channels(req, profile).status == CheckStatus.PASS


def test_resolution_unknown_when_missing_dimensions() -> None:
    from conforma.rules import check_resolution

    req = Requirement(key="resolution", expected=[1920, 1080])
    profile = _profile(video=VideoProfile(width=None, height=None))
    assert check_resolution(req, profile).status == CheckStatus.UNKNOWN


def test_bit_depth_list_expected() -> None:
    from conforma.rules import check_bit_depth

    req = Requirement(key="bit_depth", expected=[8, 10])
    profile = _profile(video=VideoProfile(bit_depth=8))
    assert check_bit_depth(req, profile).status == CheckStatus.PASS


def test_scan_type_case_insensitive() -> None:
    from conforma.rules import check_scan_type

    req = Requirement(key="scan_type", expected="Progressive")
    profile = _profile(video=VideoProfile(scan_type="progressive"))
    assert check_scan_type(req, profile).status == CheckStatus.PASS
