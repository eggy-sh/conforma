# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial scaffold: PEP 621 packaging, `src/` layout, public API surface, and
  module stubs for the deterministic conformance engine and the replykit agent
  layer.
- Two shipped delivery-spec presets (approximations): `netflix-hd`
  (HD ProRes 422 HQ) and `ebu-broadcast` (HD MXF / XDCAM HD422).
- Committed hermetic probe-JSON fixtures (ffprobe + MediaInfo) for the test
  suite; no real ffmpeg/ffprobe/media required.

## [0.1.0] - unreleased
- First public release (in progress).
