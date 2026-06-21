# conforma

**Delivery-spec compliance for post-production media — a deterministic verdict
first, an LLM only to explain it.**

`conforma` reads a delivery spec (YAML) plus a media file's probe data
(`ffprobe -print_format json` **or** MediaInfo JSON) and tells you, per
requirement, whether the file is conformant — resolution, frame rate, video
codec, bit depth, scan type, audio codec/channels/sample rate, and container.
Every failure ships with a concrete `ffmpeg` fix command. It is one of three
tools built on [replykit](https://github.com/eggy-sh/replykit), the shared
agent I/O engine behind the Post-Production Agent Kit.

```text
$ conforma check master.mov --spec netflix-hd
Netflix HD ProRes (approx.) v1.0   master.mov
✔ container        mov            mov
✔ resolution       1920x1080      1920x1080
✔ frame_rate       23.976         23.976
✗ bit_depth        10             8
    fix: ffmpeg -i master.mov -c:v prores_ks -profile:v 3 -pix_fmt yuv422p10le OUTPUT.mov
NON-CONFORMANT — 1 fail, 8 pass
```

## Why studios care (the differentiator)

QC tools that gate delivery are usually heavyweight, GUI-bound, and priced per
seat. `conforma` is the opposite, and that is the point:

1. **The verdict is deterministic and the LLM cannot touch it.** Pass/fail is
   computed by pure, total rule functions in `conforma.rules` — no model, no
   network, no subprocess. The optional [replykit](https://github.com/eggy-sh/replykit)
   agent layer can *narrate* what failed and *surface* a fix, but it can only
   relay tool-grounded facts; it can never fabricate a verdict or invent an
   unverified `ffmpeg` command. A reproducible verdict is what an ops team can
   actually put in a delivery gate.
2. **Probe-source agnostic.** ffprobe and MediaInfo JSON normalize to one
   `MediaProfile`, so the rules never branch on which tool produced the probe.
   Bring whatever your pipeline already emits.
3. **Specs are data, not code.** A delivery spec is a short YAML file. Studios
   own and version their own specs in git; `conforma show` validates them and
   `conforma check` enforces them. Two illustrative presets ship in the box
   (`netflix-hd`, `ebu-broadcast`).
4. **Automation-first.** Every command takes `--json` and prints **exactly one**
   JSON object to stdout. Exit codes are a contract (`0` conformant, `1` not,
   `2` usage error), so `conforma` drops straight into CI and agent pipelines.
5. **No heavy install to *run the checks*.** Shelling out to `ffprobe` is
   strictly optional (and only used to *generate* a probe from a real file).
   The whole engine and its test suite run off committed JSON — no ffmpeg, no
   media files, no network.

This is not a reproduction of any studio's authoritative Delivery
Specifications. The shipped presets are illustrative approximations for demos
and tests; author your own spec for real deliveries.

## Install

```bash
pip install conforma        # CLI + library (Typer, Rich, PyYAML, replykit)
```

From source, with the dev tooling:

```bash
uv venv && uv pip install -e '.[dev]'
```

## Quickstart

### CLI

```bash
# Check a probe JSON against a shipped preset.
conforma check probe_netflix_pass.json --spec netflix-hd

# Auto-probe a real media file (only when ffprobe is on PATH).
conforma check master.mov --spec ebu-broadcast

# Author your own spec; --spec also accepts a YAML path.
conforma check master.mov --spec ./netflix-custom.yaml

# Machine-readable: exactly one JSON object on stdout.
conforma check probe.json --spec netflix-hd --json | jq '.conformant'

# Write a portable Markdown report (CI artifact / PR comment).
conforma check probe.json --spec netflix-hd --report report.md

# Inspect what ships and what a spec requires.
conforma presets
conforma presets --json
conforma show netflix-hd
conforma show ./netflix-custom.yaml --json
```

Exit codes: `0` conformant, `1` non-conformant, `2` usage/IO error — so a CI
gate is just `conforma check "$probe" --spec netflix-hd`.

### Library

```python
import conforma

spec = conforma.load_preset("netflix-hd")          # or load_spec("my.yaml")
profile = conforma.load_probe("probe.json")        # ffprobe OR MediaInfo JSON

report = conforma.ConformanceAgent().check(spec, profile, input_path="master.mov")
print(report.conformant)        # bool — the deterministic verdict
print(report.counts())          # {"pass": 8, "fail": 1, "unknown": 0}
for r in report.failures:
    print(r.key, r.actual, "->", r.fix_command)
```

The agent is optional. With **no model** (the default above) you get a fully
deterministic report with fix commands. Pass a `replykit` model to add a
natural-language narrative — and keep it hermetic in tests with
`ScriptedModel`:

```python
from replykit import ScriptedModel

model = ScriptedModel(["The frame rate and bit depth are out of spec."])
summary = conforma.explain_report(report, model)   # grounded prose, no live LLM
```

## Runnable examples

Everything in [`examples/`](examples/) runs offline — no ffmpeg, no network:

```bash
python examples/check_netflix.py   # a conforming ProRes master vs. netflix-hd
python examples/check_ebu.py       # a web proxy that FAILS ebu-broadcast, with fixes
```

- [`examples/probe_netflix_pass.json`](examples/probe_netflix_pass.json) — real
  ffprobe-shaped JSON you can feed straight to `conforma check`.
- [`examples/netflix-custom.yaml`](examples/netflix-custom.yaml) — a custom
  delivery spec; pass it with `--spec examples/netflix-custom.yaml`.

## Interop & formats

| Input | Format | How |
|-------|--------|-----|
| Probe (preferred) | `ffprobe -print_format json -show_streams -show_format` | `conforma check out.json --spec …` |
| Probe (alt) | MediaInfo `--Output=JSON` | same — source is auto-detected |
| Media file | any file ffprobe can read | auto-probed **only** when `ffprobe` is on `PATH` |
| Spec | YAML (preset name or file path) | `--spec netflix-hd` or `--spec ./my.yaml` |

A path ending in `.json` is always treated as probe JSON; any other path is
auto-probed via `ffprobe` and is a clean usage error (exit `2`) when `ffprobe`
isn't installed — `conforma` never silently guesses.

**Outputs:**

- **`--json`** — a single, stable object: top-level `spec`, `media`,
  `conformant`, `counts`, and an ordered `results` list, each with
  `key` / `status` (`pass`/`fail`/`unknown`) / `expected` / `actual` /
  `message` / `severity` / `fix_command`. `json.dumps`-safe; round-trips.
- **`--report`** — portable Markdown (summary, results table, a fenced `ffmpeg`
  block per failure) — diffable and stable as a CI artifact.
- **default** — a Rich, color-coded terminal table.

### Shipped presets

| Name            | Approximates                                       |
| --------------- | -------------------------------------------------- |
| `netflix-hd`    | Netflix-style HD ProRes 422 HQ, 1080p23.976, 10-bit, 48 kHz PCM in .mov |
| `ebu-broadcast` | EBU/broadcast-style HD MXF (XDCAM HD422 MPEG-2, 1080i25), 48 kHz PCM    |

Presets are **illustrative approximations**, not official studio documents.

### Writing a spec

A spec is a `name`, a `version`, and an ordered list of `requirements`. Every
`key` must be a rule `conforma` implements
(`container`, `resolution`, `frame_rate`, `scan_type`, `video_codec`,
`bit_depth`, `audio_codec`, `audio_channels`, `audio_sample_rate`) — an unknown
key is a spec authoring error, never a silent pass.

```yaml
name: "ACME HD Mezzanine"
version: "2025.1"
requirements:
  - key: container
    expected: mov
  - key: resolution
    expected: [1920, 1080]
  - key: frame_rate
    expected: 23.976
    tolerance: 0.01
  - key: video_codec
    expected: prores          # alias-aware: matches prores_ks, etc.
  - key: bit_depth
    expected: 10
  - key: audio_sample_rate
    expected: 48000
    severity: should          # advisory, not blocking
```

Validate it without checking media: `conforma show ./acme.yaml`.

## How it fits together

```
spec.yaml ─┐
           ├─► conforma.spec ──► Spec ─┐
probe.json ┘                           ├─► rules (deterministic) ──► ConformanceReport
ffprobe/MediaInfo ─► conforma.probe ──► MediaProfile ─┘                    │
                                                       fixes (ffmpeg) ◄────┤
                                                       agent (replykit) ◄──┘  (optional narrative)
                                                                            │
                                                report_to_dict / render_report / markdown
```

The CLI (`conforma.cli`) is a thin Typer + Rich shell over the public API. It
imports only the `conforma` package root — never private internals — so the
library contract and the CLI contract are the same contract.

## Development

```bash
uv venv && uv pip install -e '.[dev]'
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=conforma --cov-report=term-missing
```

The suite is **hermetic** — no network, no live LLM, no real ffmpeg/ffprobe.
Probe data comes from committed fixtures under `tests/fixtures/`; any model is a
`replykit` `ScriptedModel`/`MockModel`. CI runs the same on Python 3.11 and 3.12
(see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Edgar Hernandez.
