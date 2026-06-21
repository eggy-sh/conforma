# conforma — Scenario Acceptance Suite

End-to-end, **hermetic** acceptance scenarios for `conforma`, the delivery-spec
compliance tool for post-production media. Every scenario below runs offline:
no network, no live LLM, no real ffmpeg/ffprobe, no NLE. All inputs are committed
fixtures (`examples/`, `tests/fixtures/`, `tests/sequence/fixtures/`); any model
is a `replykit` `ScriptedModel`/`MockModel`.

- **Repo:** `/Users/ehernand/personal_projects/postpro-kit/conforma`
- **CLI:** `/Users/ehernand/personal_projects/postpro-kit/conforma/.venv/bin/conforma`
- **Python:** `/Users/ehernand/personal_projects/postpro-kit/conforma/.venv/bin/python`

## Evaluation method

**Single consistent method: pass/fail.** A scenario passes iff *every* assertion in
its success criterion holds. Assertions are machine-checkable against one of:

1. **Process exit code** — the documented contract: `0` conformant, `1`
   non-conformant (a blocking `must` failed), `2` usage/IO error.
2. **`--json` field values** — every command emits **exactly one** JSON object on
   stdout. We assert on named fields (`conformant`, `counts.{pass,fail,unknown}`,
   per-result `status`/`expected`/`actual`/`severity`/`fix_command`/`fix_hint`).
3. **Artifact validity / round-trip** — a written `--fix` `.otio` re-parses through
   OpenTimelineIO and, when re-checked by `conforma sequence`, satisfies stated
   structural invariants (e.g. the muted reference track flips to PASS).
4. **Markdown report structure** — deterministic, diffable headings/rows/fences.

There are **no rubric / judgment-scored scenarios.** Every output under test is
produced by deterministic rule/format/timecode/DB-free code, so a pass/fail oracle
is exact. The one place a model is involved (ambiguous audio-track role inference,
S9) is asserted *negatively*: the model must **not** alter the deterministic
verdict. No scenario adds, requires, or permits a new model call; the model layer
is exercised only via `replykit.ScriptedModel`.

### AI-discipline guardrail (applies to all scenarios)

The verdict (`conformant`, every `status`, every `counts` tally) is computed by pure
functions in `conforma.rules` / `conforma.sequence.rules`. No scenario's pass
criterion may depend on model output. The model may only (a) narrate an
already-computed report (`llm_summary`) or (b) fill a `role="unknown"` audio track —
and S9 asserts that even a *wrong* model role cannot change a deterministic verdict.

---

## Capability → scenario map

| Capability | Scenarios |
|---|---|
| `check` — conformant media (ffprobe JSON, preset) | S1 |
| `check` — non-conformant media + ffmpeg fix commands | S2 |
| Probe-source agnosticism (MediaInfo JSON → same verdict) | S3 |
| Custom spec authoring + `severity: should` advisory gating | S4 |
| `presets` / `show` — spec introspection & validation | S5 |
| `sequence` — conformant editorial timeline (OTIO) | S6 |
| `sequence` — non-conformant timeline (slate + live reference) | S7 |
| `sequence --fix` — deterministic corrector + OTIO round-trip | S8 |
| Sequence model seam — ambiguous role inference (AI discipline) | S9 |
| Markdown `--report` artifact (CI) | S10 |
| Edge: unknown spec → usage error (exit 2) | S11 |
| Edge: spec with an unknown rule key → authoring error (exit 2) | S12 |

---

## S1 — `check` a conformant ProRes master against `netflix-hd`

**Capability:** media conformance, happy path.
**Kind:** passfail.

**Command**
```bash
conforma check examples/probe_netflix_pass.json --spec netflix-hd --json
```

**Success criterion (all must hold)**
- Exit code is `0`.
- stdout is exactly one parseable JSON object.
- `.conformant == true`.
- `.counts == {"pass": 9, "fail": 0, "unknown": 0}`.
- `.spec.name == "Netflix HD ProRes (approx.)"` and `.spec.version == "1.0"`.
- `.results` has length 9; **every** element has `status == "pass"` and
  `fix_command == ""`.

---

## S2 — `check` a non-conformant file emits exact ffmpeg fixes

**Capability:** non-conformant verdict + grounded fix commands.
**Kind:** passfail.

**Command**
```bash
conforma check tests/fixtures/ffprobe_netflix_fail.json --spec netflix-hd --json
```

**Success criterion (all must hold)**
- Exit code is `1`.
- `.conformant == false`.
- `.counts == {"pass": 3, "fail": 6, "unknown": 0}`.
- The result with `key == "resolution"` has `status == "fail"`,
  `actual == [1280, 720]`, `expected == [1920, 1080]`, and its `fix_command`
  contains `-vf scale=1920:1080`.
- The result with `key == "frame_rate"` has `status == "fail"` and a `fix_command`
  containing `-r 23.976`.
- The result with `key == "bit_depth"` has `status == "fail"` and a `fix_command`
  containing `-pix_fmt yuv422p10le`.
- Every `fail` result has a non-empty `fix_command`; every `pass` result has an
  empty `fix_command`.

---

## S3 — Probe-source agnosticism: MediaInfo JSON yields the same verdict

**Capability:** ffprobe **and** MediaInfo JSON normalize to one verdict.
**Kind:** passfail.

**Commands**
```bash
conforma check tests/fixtures/mediainfo_netflix_pass.json --spec netflix-hd --json
conforma check examples/probe_netflix_pass.json        --spec netflix-hd --json
```

**Success criterion (all must hold)**
- The MediaInfo run exits `0` with `.conformant == true` and
  `.counts == {"pass": 9, "fail": 0, "unknown": 0}`.
- For each `key` the per-result `status` from the MediaInfo run equals the
  `status` from the ffprobe run (S1) — i.e. the two probe sources produce an
  identical per-rule verdict map. (The `actual` strings may differ in surface
  form, e.g. container family string; `status` must match for all 9 keys.)

---

## S4 — Custom YAML spec + advisory `should` severity does not gate

**Capability:** studios author their own spec YAML; `should`-severity is advisory.
**Kind:** passfail.

**Setup** — write a temp spec `advisory.yaml`:
```yaml
name: Advisory Spec
version: "1.0"
requirements:
  - key: resolution
    expected: [1920, 1080]
  - key: audio_sample_rate
    expected: 96000
    severity: should
```

**Commands**
```bash
conforma check examples/probe_netflix_pass.json --spec <tmp>/advisory.yaml --json
conforma check examples/netflix-custom.yaml-probe ... # see note
```

**Success criterion (all must hold)**
- The advisory run loads the YAML by **path** (not a preset name) and exits `0`.
- `.conformant == true` **even though** `.counts.fail == 1` — the failing
  requirement is `audio_sample_rate` with `status == "fail"` and
  `severity == "should"`; a `should` failure must not flip the verdict.
- `.counts == {"pass": 1, "fail": 1, "unknown": 0}`.
- Re-running the same command **without** `--json` (human mode) also exits `0`.
- Control: `conforma check examples/probe_netflix_pass.json --spec
  examples/netflix-custom.yaml --json` loads a path-based custom spec
  (`.spec.name == "ACME Studios HD Mezzanine (custom)"`) and exits `1` with
  `.conformant == false` (its stricter `must` requirement fails), proving the
  path loader and `must`-gating both work.

---

## S5 — `presets` and `show` introspect and validate specs

**Capability:** spec discovery + validated introspection (schema correctness).
**Kind:** passfail.

**Commands**
```bash
conforma presets --json
conforma show netflix-hd --json
```

**Success criterion (all must hold)**
- `presets --json` exits `0`; `.presets` is a list whose `name` values are exactly
  `{"ebu-broadcast", "netflix-hd"}` (set equality); each item has integer
  `requirements == 9` and non-empty `spec_name`/`version`.
- `show netflix-hd --json` exits `0` and emits a spec object with
  `name == "Netflix HD ProRes (approx.)"`, `version == "1.0"`, and a
  `requirements` list of length 9.
- **Schema correctness:** every element of `requirements` has exactly the keys
  `{key, expected, tolerance, severity, description}`; every `key` is one of the
  9 known rule keys (`container, resolution, frame_rate, scan_type, video_codec,
  bit_depth, audio_codec, audio_channels, audio_sample_rate`); every `severity`
  is one of `{"must", "should"}`.

---

## S6 — `sequence` PASS on a conformant Netflix-IMF timeline (OTIO)

**Capability:** editorial-timeline conformance, happy path.
**Kind:** passfail.

**Command**
```bash
conforma sequence examples/seq_netflix_pass.otio --spec netflix-imf --json
```

**Success criterion (all must hold)**
- Exit code is `0`.
- `.conformant == true`.
- `.counts == {"pass": 5, "fail": 0, "unknown": 0}`.
- The 5 result keys, in order, are
  `["slate_present", "slate_duration", "reference_audio_muted",
    "video_track_count", "audio_track_count"]`, all `status == "pass"`.
- `slate_duration` result has `actual == 5.0` (the 5 s head slate is recognized).
- `reference_audio_muted` result has `actual == "all muted"` (the scratch stem is
  correctly detected as a reference role **and** found muted).

---

## S7 — `sequence` FAIL: short slate + live reference stem

**Capability:** sequence non-conformance with deterministic fix hints.
**Kind:** passfail.

**Command**
```bash
conforma sequence examples/seq_netflix_fail.otio --spec netflix-imf --json
```

**Success criterion (all must hold)**
- Exit code is `1`.
- `.conformant == false`.
- `.counts == {"pass": 3, "fail": 2, "unknown": 0}`.
- `slate_duration` result has `status == "fail"`, `actual == 2.0`,
  `expected == 5.0`, and a non-empty `fix_hint` containing `5s`.
- `reference_audio_muted` result has `status == "fail"`, `actual` equal to the
  JSON list `["A4 REF 2pop scratch"]`, and a `fix_hint` containing `Mute`.
- `video_track_count` and `audio_track_count` results are both `status == "pass"`.

---

## S8 — `sequence --fix` writes a corrected, round-tripping OTIO

**Capability:** deterministic corrector; OTIO write/round-trip; flag-not-fabricate.
**Kind:** passfail.

**Commands**
```bash
conforma sequence examples/seq_netflix_fail.otio --spec netflix-imf \
  --fix <tmp>/fixed.otio --json          # writes the corrected timeline
conforma sequence <tmp>/fixed.otio --spec netflix-imf --json   # re-check
```

**Success criterion (all must hold)**
- The first command exits `1` (the input is still non-conformant; `--fix` does not
  change the input's verdict) and creates `<tmp>/fixed.otio`.
- `<tmp>/fixed.otio` re-parses cleanly via
  `opentimelineio.adapters.read_from_file` (valid OTIO).
- In the parsed fixed timeline, the audio track named `A4 REF 2pop scratch` has its
  native `enabled == False` (the deterministic mute), while the other audio tracks
  remain `enabled == True`.
- The **re-check** run reports `reference_audio_muted` with `status == "pass"`
  (the mute took effect) **but** `slate_duration` still `status == "fail"` — the
  corrector *flags* the over/under-length slate and never fabricates frames.
  Consequently the re-check still exits `1` with
  `.counts == {"pass": 4, "fail": 1, "unknown": 0}`.

---

## S9 — Sequence model seam: ambiguous role inference cannot change the verdict

**Capability:** the **only** model use (fuzzy audio role for `role="unknown"`
tracks); AI-discipline guardrail.
**Kind:** passfail. **Hermetic:** `replykit.ScriptedModel` only — no live LLM.

**Procedure (library, hermetic)**
```python
import conforma
from replykit import ScriptedModel
tl = conforma.read_timeline("tests/sequence/fixtures/seq_2pop_ambiguous.otio")
layout = conforma.extract_layout(tl, source="amb.otio")
spec = conforma.load_seq_preset("netflix-imf")

det = conforma.SequenceConformanceAgent().check(spec, layout)            # no model
model = ScriptedModel(["music"] * 8 + ["narrative"])  # deliberately WRONG role
mod = conforma.SequenceConformanceAgent(model).check(spec, layout)       # with model
```

**Success criterion (all must hold)**
- In `layout`, exactly the track named `Stem Foxtrot` has `role == "unknown"`
  (the deterministic extractor resolved `REF 2pop temp`→`reference`, `DX`→
  `dialogue`, `M&E`→`me` on keywords; the bare stem is the genuine gap).
- The per-rule verdict map `{key: (status, actual)}` is **identical** between `det`
  and `mod` — the model (even with a wrong "music" answer) does not change any
  deterministic verdict; `det.conformant == mod.conformant`.
- `det.llm_summary == ""` (no model → no narrative); `mod.llm_summary` is a
  non-empty string (the model narrates the already-computed report).
- A second run classifying the ambiguous stem as `"reference"`
  (`ScriptedModel(["reference"]*8 + ["..."])`) still does **not** flip
  `reference_audio_muted` away from its deterministic outcome on the
  already-resolved `REF 2pop temp` track (the deterministic match always wins).

---

## S10 — Markdown `--report` is a stable, structured CI artifact

**Capability:** portable Markdown report.
**Kind:** passfail.

**Command**
```bash
conforma check tests/fixtures/ffprobe_netflix_fail.json --spec netflix-hd \
  --report <tmp>/r.md --json
```

**Success criterion (all must hold)**
- Exit code is `1`; `<tmp>/r.md` exists.
- The file's first line is exactly
  `# Conformance report: Netflix HD ProRes (approx.) v1.0`.
- It contains a line `- **Verdict:** ❌ NON-CONFORMANT` and a line
  `- **Counts:** 3 pass / 6 fail / 0 unknown`.
- It contains a `## Results` heading and a Markdown table whose header row is
  `| Requirement | Status | Expected | Actual | Detail |`.
- It contains a `## Suggested fixes` section with exactly 6 fenced
  ```` ```ffmpeg ```` code blocks (one per `must` failure).

---

## S11 — Edge: unknown spec is a clean usage error (exit 2)

**Capability:** failure handling — unknown preset / unreadable spec.
**Kind:** passfail.

**Command**
```bash
conforma check examples/probe_netflix_pass.json --spec does-not-exist --json
```

**Success criterion (all must hold)**
- Exit code is `2` (usage error — distinct from `0`/`1` verdicts).
- stdout is exactly one JSON object with a single key `error` whose value mentions
  both that the name is not a shipped preset and lists the available presets
  (contains the substrings `netflix-hd` and `ebu-broadcast`).
- No verdict keys (`conformant`, `counts`, `results`) are present in the object.

---

## S12 — Edge: a spec with an unknown rule key is an authoring error (exit 2)

**Capability:** failure handling — spec validation rejects unknown rule keys.
**Kind:** passfail.

**Setup** — write a temp spec `bad.yaml`:
```yaml
name: Bad Spec
version: "1.0"
requirements:
  - key: not_a_real_rule
    expected: 1
```

**Command**
```bash
conforma show <tmp>/bad.yaml --json
```

**Success criterion (all must hold)**
- Exit code is `2`.
- stdout is exactly one JSON object `{"error": ...}` whose message names the
  offending key `not_a_real_rule` and enumerates the known rule keys (an unknown
  key is never silently treated as a pass).

---

## Running the suite

All scenarios are hermetic and use only committed fixtures plus `replykit`'s
`ScriptedModel`/`MockModel`. CLI scenarios assert on `$?` and the single stdout
JSON object; library scenarios (S8 re-parse, S9) call the public `conforma` API and
`opentimelineio` directly. No scenario requires network, a live LLM, ffmpeg, or an
NLE. A harness should treat a scenario as **pass** only when every bullet in its
success criterion holds.
