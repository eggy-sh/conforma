"""Unit tests for the deterministic ffmpeg fix generator (:mod:`conforma.fixes`)."""

from __future__ import annotations

from conforma.fixes import INPUT_PLACEHOLDER, OUTPUT_PLACEHOLDER, suggest_fix
from conforma.models import CheckStatus, RuleResult


def _fail(key: str, expected: object) -> RuleResult:
    return RuleResult(
        key=key,
        status=CheckStatus.FAIL,
        expected=expected,
        actual="wrong",
        message=f"{key} failed",
    )


def test_placeholders_are_documented_constants() -> None:
    assert INPUT_PLACEHOLDER == "INPUT"
    assert OUTPUT_PLACEHOLDER == "OUTPUT"


def test_pass_and_unknown_return_empty() -> None:
    passing = RuleResult(
        key="resolution",
        status=CheckStatus.PASS,
        expected=[1920, 1080],
        actual=[1920, 1080],
        message="ok",
    )
    unknown = RuleResult(
        key="bit_depth",
        status=CheckStatus.UNKNOWN,
        expected=10,
        actual=None,
        message="unknown",
    )
    assert suggest_fix(passing) == ""
    assert suggest_fix(unknown) == ""


def test_unknown_key_returns_empty() -> None:
    result = _fail("not_a_real_key", "x")
    assert suggest_fix(result) == ""


def test_resolution_fix_has_scale() -> None:
    cmd = suggest_fix(_fail("resolution", [1920, 1080]))
    assert "scale=1920:1080" in cmd
    assert "ffmpeg" in cmd


def test_frame_rate_fix_has_r_flag() -> None:
    cmd = suggest_fix(_fail("frame_rate", 23.976))
    assert "-r 23.976" in cmd


def test_video_codec_fix_has_cv_flag() -> None:
    cmd = suggest_fix(_fail("video_codec", "prores"))
    assert "-c:v prores_ks" in cmd


def test_bit_depth_fix_has_pix_fmt() -> None:
    cmd = suggest_fix(_fail("bit_depth", 10))
    assert "-pix_fmt" in cmd
    assert "10le" in cmd


def test_audio_codec_fix_has_ca_flag() -> None:
    cmd = suggest_fix(_fail("audio_codec", "pcm"))
    assert "-c:a pcm_s24le" in cmd


def test_audio_channels_fix_has_ac_flag() -> None:
    cmd = suggest_fix(_fail("audio_channels", 2))
    assert "-ac 2" in cmd


def test_audio_sample_rate_fix_has_ar_flag() -> None:
    cmd = suggest_fix(_fail("audio_sample_rate", 48000))
    assert "-ar 48000" in cmd


def test_container_fix_changes_extension() -> None:
    cmd = suggest_fix(_fail("container", "mov"), output_path="out.mp4")
    assert cmd.endswith("out.mov")
    assert "-c copy" in cmd


def test_scan_type_fix_progressive_and_interlaced() -> None:
    prog = suggest_fix(_fail("scan_type", "progressive"))
    inter = suggest_fix(_fail("scan_type", "interlaced"))
    assert "yadif" in prog
    assert "ilme" in inter


def test_path_substitution() -> None:
    cmd = suggest_fix(_fail("frame_rate", 24.0), input_path="in.mov", output_path="out.mov")
    assert "in.mov" in cmd
    assert "out.mov" in cmd
    assert "INPUT" not in cmd
    assert "OUTPUT" not in cmd


def test_idempotent_byte_identical() -> None:
    result = _fail("resolution", [1920, 1080])
    first = suggest_fix(result, input_path="a.mov", output_path="b.mov")
    second = suggest_fix(result, input_path="a.mov", output_path="b.mov")
    assert first == second


def test_resolution_fix_empty_when_expected_malformed() -> None:
    assert suggest_fix(_fail("resolution", [1920])) == ""
