# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-20

First public release of `conforma` — a delivery-spec compliance agent for
post-production media, built on [replykit](https://github.com/edgarh92/replykit).
The verdict is always computed by deterministic, total rule functions; the
optional replykit model layer may only narrate the result or fill a genuinely
ambiguous audio-track role — it can never fabricate or override a verdict.

### Added

- **File-level conformance (`conforma check`).** Reads a media file's probe data
  (`ffprobe -print_format json` **or** MediaInfo JSON) plus a delivery spec and
  reports per-requirement conformance across nine rule keys: `resolution`,
  `frame_rate`, `video_codec`, `bit_depth`, `scan_type`, `audio_codec`,
  `audio_channels`, `audio_sample_rate`, and `container`. Each `must` failure
  ships with a concrete `ffmpeg` fix command. Optional auto-probing shells out to
  `ffprobe` only to *generate* a probe from a real file; the engine itself never
  requires ffmpeg or media.
- **Probe-source agnosticism.** ffprobe and MediaInfo JSON normalize to one
  `MediaProfile`, so the rules produce the same per-requirement verdict
  regardless of which tool emitted the probe.
- **Specs as data.** Delivery specs are short YAML files with `must`/`should`
  severities; a `should` failure is advisory and does not flip the overall
  verdict. `conforma show` validates a spec (preset name or path) and rejects an
  unknown rule key as an authoring error; `conforma presets` lists the shipped
  presets. Two illustrative presets ship in the box: `netflix-hd`
  (HD ProRes 422 HQ) and `ebu-broadcast` (HD MXF / XDCAM HD422). These are
  approximations for demos and tests, not any studio's authoritative spec.
- **Sequence-level conformance (`conforma sequence`, the `conform_validator`
  feature).** Checks an **exported editorial timeline** — Final Cut `.fcpxml`,
  Avid `.aaf`, or OpenTimelineIO `.otio` — against a sequence delivery spec, for
  the editorial defects a file probe cannot see:
  - **Rules:** `slate_present`, `slate_duration` (within tolerance of the
    required head-slate length), `reference_audio_muted` (no scratch/temp/2pop
    reference stem left live), `video_track_count`, and `audio_track_count` —
    all computed by pure functions in `conforma.sequence.rules` from a small,
    JSON-serializable `SequenceLayout`. No LLM, NLE, or media involved.
  - **One OTIO seam.** Only `conforma.sequence.otio_io` imports
    `opentimelineio`; it reads FCPXML/AAF/OTIO into a single normalized
    `Timeline` (an FCPXML *library* collection is reduced to its first timeline)
    so everything downstream speaks a dependency-free layout. A missing
    FCPXML/AAF adapter exits `2` with an install hint instead of a stack trace.
  - **Audio-role inference is literal first, model-assisted only at the
    boundary.** Track roles (`reference`/`me`/`dialogue`/`music`) come from an
    explicit keyword set plus any explicit FCPXML `audioRole`; the replykit model
    is consulted **only** for tracks the keyword matcher left `unknown`, and the
    deterministic match always wins.
  - **Deterministic corrector (`--fix`).** Writes a corrected timeline that
    natively disables (mutes) the offending reference track and annotates an
    over/under-length slate with a `conforma_flag` note. It flags; it never
    fabricates frames. `otio_json` output round-trips track names and enable
    flags losslessly. Ships the `netflix-imf` sequence preset.
- **Automation-first contracts.** Every command accepts `--json` and prints
  **exactly one** JSON object to stdout, supports a Markdown `--report` artifact,
  and uses stable exit codes as a contract: `0` conformant, `1` non-conformant,
  `2` usage/IO/authoring error.
- **Packaging & quality.** PEP 621 packaging (hatchling) with a `src/` layout, a
  typed public API (`py.typed`), and `opentimelineio` as a core dependency with
  FCPXML/AAF adapters available via the `adapters` extra. Hermetic test suite
  (committed ffprobe/MediaInfo JSON probes and `.otio`/`.fcpxml` timelines; no
  real ffmpeg/ffprobe/NLE/network) plus a CI pipeline running `ruff` and
  `pytest` on Python 3.11 and 3.12.

[Unreleased]: https://github.com/edgarh92/conforma/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/edgarh92/conforma/releases/tag/v0.1.0
