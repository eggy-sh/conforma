"""Unit tests for probe normalization (:mod:`conforma.probe`)."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from conforma import probe as probe_mod
from conforma.errors import ProbeError
from conforma.probe import (
    ProbeSource,
    detect_probe_source,
    ffprobe_available,
    load_probe,
    normalize_probe,
    parse_frame_rate,
    probe_media,
)


def test_detect_probe_source_ffprobe(ffprobe_netflix_pass: dict[str, Any]) -> None:
    assert detect_probe_source(ffprobe_netflix_pass) is ProbeSource.FFPROBE


def test_detect_probe_source_mediainfo(mediainfo_netflix_pass: dict[str, Any]) -> None:
    assert detect_probe_source(mediainfo_netflix_pass) is ProbeSource.MEDIAINFO


def test_detect_probe_source_unknown() -> None:
    assert detect_probe_source({"unrelated": 1}) is ProbeSource.UNKNOWN
    assert detect_probe_source({"media": {"track": "not-a-list"}}) is ProbeSource.UNKNOWN
    assert detect_probe_source([]) is ProbeSource.UNKNOWN  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("24000/1001", 23.976),
        ("25/1", 25.0),
        ("0/0", None),
        ("30", 30.0),
        (30, 30.0),
        (29.97, 29.97),
        ("", None),
        (None, None),
        ("not-a-rate", None),
        (0, None),
        ("0", None),
        (True, None),
    ],
)
def test_parse_frame_rate(value: Any, expected: float | None) -> None:
    result = parse_frame_rate(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected, abs=1e-3)


def test_normalize_ffprobe_netflix(ffprobe_netflix_pass: dict[str, Any]) -> None:
    profile = normalize_probe(ffprobe_netflix_pass)
    assert profile.container == "mov,mp4,m4a,3gp,3g2,mj2"
    assert profile.source == "ffprobe"
    assert profile.video is not None
    assert profile.video.codec == "prores"
    assert profile.video.width == 1920
    assert profile.video.height == 1080
    assert profile.video.frame_rate == pytest.approx(23.976, abs=1e-3)
    assert profile.video.bit_depth == 10
    assert profile.video.scan_type == "progressive"
    assert len(profile.audio) == 1
    assert profile.audio[0].codec == "pcm_s24le"
    assert profile.audio[0].channels == 2
    assert profile.audio[0].sample_rate == 48000
    assert profile.audio[0].language == "eng"
    assert profile.duration_seconds == pytest.approx(120.52)


def test_normalize_mediainfo_equivalent_to_ffprobe(
    ffprobe_netflix_pass: dict[str, Any],
    mediainfo_netflix_pass: dict[str, Any],
) -> None:
    ff = normalize_probe(ffprobe_netflix_pass)
    mi = normalize_probe(mediainfo_netflix_pass)
    assert mi.source == "mediainfo"
    assert mi.video is not None and ff.video is not None
    # codec families align (prores), dimensions, fps, bit depth equal
    assert mi.video.width == ff.video.width
    assert mi.video.height == ff.video.height
    assert mi.video.bit_depth == ff.video.bit_depth == 10
    assert mi.video.frame_rate == pytest.approx(ff.video.frame_rate, abs=1e-3)
    assert mi.video.scan_type == ff.video.scan_type == "progressive"
    assert mi.container == "mov"
    assert mi.audio[0].channels == ff.audio[0].channels == 2
    assert mi.audio[0].sample_rate == ff.audio[0].sample_rate == 48000


def test_normalize_sparse_unknowns(ffprobe_sparse: dict[str, Any]) -> None:
    profile = normalize_probe(ffprobe_sparse)
    assert profile.video is not None
    assert profile.video.bit_depth is None
    assert profile.video.scan_type is None
    assert profile.audio == []


def test_normalize_probe_source_override(ffprobe_netflix_pass: dict[str, Any]) -> None:
    profile = normalize_probe(ffprobe_netflix_pass, source="custom-path")
    assert profile.source == "custom-path"


def test_normalize_probe_unrecognized_shape_raises() -> None:
    with pytest.raises(ProbeError, match="Unrecognized probe"):
        normalize_probe({"nothing": "here"})


def test_load_probe_reads_file(fixture_path: Any) -> None:
    profile = load_probe(fixture_path("ffprobe_netflix_pass"))
    assert profile.video is not None
    assert profile.video.codec == "prores"
    assert profile.source.endswith("ffprobe_netflix_pass.json")


def test_load_probe_missing_file_raises() -> None:
    with pytest.raises(ProbeError, match="Could not read"):
        load_probe("/no/such/probe.json")


def test_load_probe_invalid_json_raises(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProbeError, match="Invalid JSON"):
        load_probe(str(bad))


def test_load_probe_non_object_raises(tmp_path) -> None:
    bad = tmp_path / "list.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ProbeError):
        load_probe(str(bad))


def test_ffprobe_available_uses_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_mod.shutil, "which", lambda _name: "/usr/bin/ffprobe")
    assert ffprobe_available() is True
    monkeypatch.setattr(probe_mod.shutil, "which", lambda _name: None)
    assert ffprobe_available() is False


def test_probe_media_absent_ffprobe_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_mod, "ffprobe_available", lambda: False)
    with pytest.raises(ProbeError, match="not available"):
        probe_media("master.mov")


def _fake_run_factory(returncode: int, stdout: str = "", stderr: str = ""):
    def _fake_run(*_args: Any, **_kwargs: Any):
        return subprocess.CompletedProcess(
            args=["ffprobe"], returncode=returncode, stdout=stdout, stderr=stderr
        )

    return _fake_run


def test_probe_media_success(
    monkeypatch: pytest.MonkeyPatch, ffprobe_netflix_pass: dict[str, Any]
) -> None:
    monkeypatch.setattr(probe_mod, "ffprobe_available", lambda: True)
    payload = json.dumps(ffprobe_netflix_pass)
    monkeypatch.setattr(probe_mod.subprocess, "run", _fake_run_factory(0, stdout=payload))
    profile = probe_media("master.mov")
    assert profile.video is not None
    assert profile.video.codec == "prores"
    assert profile.source == "master.mov"


def test_probe_media_nonzero_exit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_mod, "ffprobe_available", lambda: True)
    monkeypatch.setattr(probe_mod.subprocess, "run", _fake_run_factory(1, stderr="boom"))
    with pytest.raises(ProbeError, match="exited 1"):
        probe_media("master.mov")


def test_probe_media_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_mod, "ffprobe_available", lambda: True)

    def _raise_timeout(*_args: Any, **_kwargs: Any):
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=30.0)

    monkeypatch.setattr(probe_mod.subprocess, "run", _raise_timeout)
    with pytest.raises(ProbeError, match="timed out"):
        probe_media("master.mov", timeout=30.0)


def test_probe_media_bad_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_mod, "ffprobe_available", lambda: True)
    monkeypatch.setattr(probe_mod.subprocess, "run", _fake_run_factory(0, stdout="{not json"))
    with pytest.raises(ProbeError, match="unparseable JSON"):
        probe_media("master.mov")


def test_probe_media_oserror_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_mod, "ffprobe_available", lambda: True)

    def _raise_oserror(*_args: Any, **_kwargs: Any):
        raise OSError("no exec")

    monkeypatch.setattr(probe_mod.subprocess, "run", _raise_oserror)
    with pytest.raises(ProbeError, match="Could not run ffprobe"):
        probe_media("master.mov")


# --- Normalization edge cases ---------------------------------------------


def test_ffprobe_interlaced_field_orders() -> None:
    for fo, expected in (
        ("tt", "interlaced"),
        ("bb", "interlaced"),
        ("progressive", "progressive"),
        ("unknown", None),
        ("weird", None),
    ):
        data = {"streams": [{"codec_type": "video", "field_order": fo}], "format": {}}
        profile = normalize_probe(data)
        assert profile.video is not None
        assert profile.video.scan_type == expected, fo


def test_ffprobe_bit_depth_from_pix_fmt_when_absent() -> None:
    # No bits_per_raw_sample, but pix_fmt implies 10-bit.
    data = {
        "streams": [{"codec_type": "video", "pix_fmt": "yuv422p10le"}],
        "format": {},
    }
    profile = normalize_probe(data)
    assert profile.video is not None
    assert profile.video.bit_depth == 10


def test_ffprobe_skips_non_dict_streams() -> None:
    data = {
        "streams": ["not-a-dict", {"codec_type": "video", "width": 640, "height": 480}],
        "format": {"format_name": "mov", "duration": "bad-number"},
    }
    profile = normalize_probe(data)
    assert profile.video is not None
    assert profile.video.width == 640
    assert profile.duration_seconds is None  # unparseable duration -> None


def test_mediainfo_interlaced_and_general_format_fallback() -> None:
    data = {
        "media": {
            "track": [
                "not-a-dict",
                {"@type": "General", "Format": "MXF", "Duration": "12.0"},
                {
                    "@type": "Video",
                    "Format": "MPEG-2 Video",
                    "Width": "1920",
                    "Height": "1080",
                    "ScanType": "Interlaced",
                    "BitDepth": "8",
                },
            ]
        }
    }
    profile = normalize_probe(data)
    assert profile.video is not None
    assert profile.video.scan_type == "interlaced"
    assert profile.container == "MXF"  # falls back to General.Format when no FileExtension
    assert profile.duration_seconds == 12.0
    assert profile.audio == []
