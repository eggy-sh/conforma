# conforma — Acceptance Evidence

Hermetic, reproducible acceptance run of **all 12 scenarios** (S1–S12) from
`acceptance/scenarios.md`. Every scenario runs offline under identical conditions:
no network, no live LLM, no real ffmpeg/ffprobe/NLE. All inputs are committed
fixtures; the one model seam (S9) uses only `replykit.ScriptedModel`.

- **Repo:** `/Users/ehernand/personal_projects/postpro-kit/conforma`
- **Runner:** `acceptance/test_acceptance.py` (pytest module; one test per scenario id)
- **CLI under test:** `.venv/bin/conforma` (subprocess), library API for S8 re-parse + S9
- **replykit:** editable install from `/Users/ehernand/personal_projects/postpro-kit/replykit`

## How to run

```bash
cd /Users/ehernand/personal_projects/postpro-kit/conforma
.venv/bin/python -m pytest acceptance/test_acceptance.py -v
```

## Hermetic conditions (enforced identically for every scenario)

- CLI scenarios run as a subprocess in a **scrubbed environment**:
  - `PATH` is rebuilt with every directory containing `ffmpeg`/`ffprobe` removed,
    then the project `.venv/bin` prepended. (Host PATH *does* expose
    `/opt/homebrew/bin/ffprobe`, so this scrubbing is load-bearing — it forces the
    CLI onto the committed `*.json`/`*.otio` fixtures and prevents any auto-probe.)
  - Network/proxy/API-key vars are cleared (`http(s)_proxy`, `*_PROXY`,
    `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`), `NO_PROXY=*`.
  - A session-scoped guardrail asserts `shutil.which("ffprobe"|"ffmpeg")` resolves
    to nothing under the test PATH before any scenario runs.
- Library scenarios (S8 OTIO re-parse, S9 model seam) call only the public
  `conforma` API + `opentimelineio`, and where a model is needed a
  `replykit.ScriptedModel` (no live LLM, no network).
- `--json` output is parsed with `json.loads(stdout)` over the **whole** stdout,
  which enforces "exactly one JSON object and nothing else".

## Result summary

| Scenario | Capability | Verdict |
|---|---|---|
| S1 | `check` conformant ProRes vs `netflix-hd`, deterministic JSON verdict | **PASS** |
| S2 | non-conformant report with per-failure ffmpeg fix commands | **PASS** |
| S3 | probe-source agnosticism: MediaInfo == ffprobe per-rule verdict | **PASS** |
| S4 | custom YAML by path; `must` vs `should` severity gating | **PASS** |
| S5 | `presets` + `show` introspection / schema correctness | **PASS** |
| S6 | `sequence` PASS on conformant Netflix-IMF OTIO | **PASS** |
| S7 | `sequence` FAIL: short slate + live reference stem | **PASS** |
| S8 | `sequence --fix` deterministic corrector + OTIO round-trip | **PASS** |
| S9 | model seam: ambiguous role inference cannot change a verdict | **PASS** |
| S10 | Markdown `--report` CI artifact structure | **PASS** |
| S11 | unknown spec -> usage error (exit 2) | **PASS** |
| S12 | unknown rule key -> authoring error (exit 2) | **PASS** |

**Totals: 12 / 12 PASS, 0 FAIL.** Reproduced across consecutive runs
(`12 passed` each time, ~1.8s).

## Full-suite verification (latest hardening run, 2026-06-20)

Run after the sign-off remediations below, with replykit installed editable from
the sibling repo (`/Users/ehernand/personal_projects/postpro-kit/replykit`):

| Gate | Command | Result |
|---|---|---|
| Acceptance scenarios | `.venv/bin/python -m pytest acceptance/test_acceptance.py -q` | **12 passed** |
| Unit/integration suite | `.venv/bin/python -m pytest -q` | **318 passed** (4 third-party `DeprecationWarning`s only) |
| Lint | `.venv/bin/ruff check .` | **All checks passed** |
| Format | `.venv/bin/ruff format --check .` | **47 files already formatted** |

### Sign-off remediations applied this run (no scenario weakened, no new model call)

- **CHANGELOG.md rewritten into an accurate `[0.1.0] - 2026-06-20` entry** that
  documents both the file-level `check` engine and the sequence-conformance
  (`conform_validator`) feature — `conforma sequence`, its five deterministic
  rules, the single OTIO seam, literal-first audio-role inference, and the
  deterministic `--fix` corrector. The stale "module stubs" /
  "[0.1.0] - unreleased" text is gone.
- **CI replykit install made resolvable.** Because replykit is not yet on PyPI,
  `.github/workflows/ci.yml` now installs it from git
  (`replykit @ git+https://github.com/eggy-sh/replykit@main`) before installing
  conforma, so CI is green once both repos are pushed to `eggy-sh`. The previous
  non-resolvable sibling-checkout path is removed; local/dev still uses the
  editable sibling install. CHANGELOG/README replykit links point at `eggy-sh`.
- **`acceptance/test_acceptance.py` reformatted** so the repo-wide
  `ruff format --check .` gate (which CI runs over the whole tree) is clean.
  Whitespace/line-wrapping only — no assertion, command, or success criterion
  changed; the 12 scenarios are byte-for-byte the same checks.

The AI-discipline guardrail is unchanged: every verdict is still computed by the
deterministic pure functions in `conforma.rules` / `conforma.sequence.rules`, and
the only model seam (S9) remains hermetic via `replykit.ScriptedModel`.

---

## S1 — `check` conformant ProRes vs `netflix-hd`

**Command**
```bash
conforma check examples/probe_netflix_pass.json --spec netflix-hd --json
```

**Captured output (exit 0, single JSON object)**
- `.conformant == true`; `.counts == {"pass":9,"fail":0,"unknown":0}`.
- `.spec.name == "Netflix HD ProRes (approx.)"`, `.spec.version == "1.0"`.
- `.results` length 9; every element `status == "pass"` and `fix_command == ""`.

**Verdict: PASS** — all criteria hold.

---

## S2 — non-conformant file emits exact ffmpeg fixes

**Command**
```bash
conforma check tests/fixtures/ffprobe_netflix_fail.json --spec netflix-hd --json
```

**Captured output (exit 1, single JSON object)**
- `.conformant == false`; `.counts == {"pass":3,"fail":6,"unknown":0}`.
- `resolution`: `status=fail`, `actual=[1280,720]`, `expected=[1920,1080]`,
  `fix_command` contains `-vf scale=1920:1080`
  (`ffmpeg -i ... -vf scale=1920:1080 -c:a copy OUTPUT`).
- `frame_rate` fail `fix_command` contains `-r 23.976`.
- `bit_depth` fail `fix_command` contains `-pix_fmt yuv422p10le`.
- Every `fail` has a non-empty `fix_command`; every `pass` has `fix_command == ""`.

**Verdict: PASS** — all criteria hold.

---

## S3 — probe-source agnosticism (MediaInfo == ffprobe verdict)

**Commands**
```bash
conforma check tests/fixtures/mediainfo_netflix_pass.json --spec netflix-hd --json
conforma check examples/probe_netflix_pass.json          --spec netflix-hd --json
```

**Captured output**
- MediaInfo run: exit 0, `.conformant == true`, `.counts == {"pass":9,"fail":0,"unknown":0}`.
- Per-key `status` map is **set-equal across all 9 keys** to the ffprobe run from
  S1, independent of surface-form `actual` differences (e.g. container is
  `"mov"` from MediaInfo vs `"mov,mp4,m4a,3gp,3g2,mj2"` from ffprobe; codec
  `"ProRes"` vs `"prores"`). Both maps: all 9 keys `pass`.

**Verdict: PASS** — identical per-rule verdict across both probe sources.

---

## S4 — custom YAML spec by path + `should` advisory gating

**Setup (temp file written by the test)** — `advisory.yaml` with a `must`
`resolution` requirement and a `should` `audio_sample_rate == 96000` requirement
(which the conformant probe fails).

**Commands**
```bash
conforma check examples/probe_netflix_pass.json --spec <tmp>/advisory.yaml --json
conforma check examples/probe_netflix_pass.json --spec <tmp>/advisory.yaml         # human mode
conforma check examples/probe_netflix_pass.json --spec examples/netflix-custom.yaml --json  # control
```

**Captured output**
- Advisory `--json`: exit 0; `.conformant == true` **even though** `.counts.fail == 1`;
  `.counts == {"pass":1,"fail":1,"unknown":0}`; the failing requirement is
  `audio_sample_rate` with `status == "fail"` and `severity == "should"`
  (a `should` failure does not flip the verdict).
- Advisory **human mode** (no `--json`): exit 0.
- Control (`examples/netflix-custom.yaml` by path): exit 1, `.conformant == false`,
  `.spec.name == "ACME Studios HD Mezzanine (custom)"` — its stricter `must`
  (`frame_rate == 25`) gates.

**Verdict: PASS** — path loader, `should` advisory, and `must` gating all behave.

---

## S5 — `presets` + `show` introspection / schema correctness

**Commands**
```bash
conforma presets --json
conforma show netflix-hd --json
```

**Captured output**
- `presets --json` exit 0; `.presets` name set is exactly
  `{ebu-broadcast, netflix-hd}`; each item `requirements == 9` (int) with non-empty
  `spec_name`/`version`.
- `show netflix-hd --json` exit 0; `name == "Netflix HD ProRes (approx.)"`,
  `version == "1.0"`, `requirements` length 9.
- **Schema:** every requirement element has exactly the key set
  `{key, expected, tolerance, severity, description}`; every `key` is one of the 9
  known rule keys; every `severity` in `{must, should}`.

**Verdict: PASS** — all criteria hold.

---

## S6 — `sequence` PASS on conformant Netflix-IMF OTIO

**Command**
```bash
conforma sequence examples/seq_netflix_pass.otio --spec netflix-imf --json
```

**Captured output (exit 0, single JSON object)**
- `.conformant == true`; `.counts == {"pass":5,"fail":0,"unknown":0}`.
- Result keys in order: `[slate_present, slate_duration, reference_audio_muted,
  video_track_count, audio_track_count]`, all `status == "pass"`.
- `slate_duration.actual == 5.0`; `reference_audio_muted.actual == "all muted"`.

**Verdict: PASS** — all criteria hold.

---

## S7 — `sequence` FAIL: short slate + live reference stem

**Command**
```bash
conforma sequence examples/seq_netflix_fail.otio --spec netflix-imf --json
```

**Captured output (exit 1, single JSON object)**
- `.conformant == false`; `.counts == {"pass":3,"fail":2,"unknown":0}`.
- `slate_duration`: `status=fail`, `actual=2.0`, `expected=5.0`, `fix_hint`
  non-empty and contains `5s` (`"Trim or extend the slate clip to 5s (±0.5s)."`).
- `reference_audio_muted`: `status=fail`, `actual == ["A4 REF 2pop scratch"]`,
  `fix_hint` contains `Mute`.
- `video_track_count` and `audio_track_count` both `status == "pass"`.

**Verdict: PASS** — all criteria hold.

---

## S8 — `sequence --fix` deterministic corrector + OTIO round-trip

**Commands**
```bash
conforma sequence examples/seq_netflix_fail.otio --spec netflix-imf \
  --fix <tmp>/fixed.otio --json        # writes corrected timeline
conforma sequence <tmp>/fixed.otio --spec netflix-imf --json   # re-check
```

**Captured output / artifact**
- First command exits **1** (input verdict unchanged) and creates `<tmp>/fixed.otio`.
- `<tmp>/fixed.otio` re-parses cleanly via `opentimelineio.adapters.read_from_file`.
  In the parsed timeline the audio tracks are:
  `A1 Dialogue=True, A2 Music=True, A3 M&E=True, A4 REF 2pop scratch=False` — the
  reference stem is natively disabled, the others remain enabled.
- Re-check exits **1** with `.counts == {"pass":4,"fail":1,"unknown":0}`;
  `reference_audio_muted` flipped to `pass` (mute took effect) while
  `slate_duration` is still `fail` (the corrector flags the under-length slate and
  never fabricates frames).

**Verdict: PASS** — corrector mutes the reference, round-trips valid OTIO, and
flags-not-fabricates the slate.

---

## S9 — model seam: ambiguous role inference cannot change a verdict

**Procedure (hermetic library; `replykit.ScriptedModel` only)** on
`tests/sequence/fixtures/seq_2pop_ambiguous.otio` against `netflix-imf`.

**Captured output**
- Extracted layout audio roles: `REF 2pop temp -> reference`, `DX -> dialogue`,
  `M&E -> me` (deterministic keyword resolution); **exactly** `Stem Foxtrot` has
  `role == "unknown"` (the genuine gap).
- No-model run vs with-model run (model returns the **wrong** role `"music"` for
  the ambiguous stem): the per-rule verdict map `{key:(status,actual)}` is
  **identical**, and `det.conformant == mod.conformant` — the model cannot change a
  deterministic verdict even with a wrong answer.
- `det.llm_summary == ""` (no model -> no narrative); `mod.llm_summary` is a
  non-empty string (the model narrates the already-computed report).
- A further run classifying the ambiguous stem as `"reference"` does **not** flip
  the already-resolved `REF 2pop temp` track away from its deterministic outcome:
  `reference_audio_muted` stays `fail` and `REF 2pop temp` stays in the failing
  `actual` list (the deterministic match always wins).
- No live LLM or network used (ScriptedModel only).

**Verdict: PASS** — AI-discipline guardrail holds; the model only narrates / fills
a genuine gap and never overrides a deterministic verdict.

---

## S10 — Markdown `--report` CI artifact

**Command**
```bash
conforma check tests/fixtures/ffprobe_netflix_fail.json --spec netflix-hd \
  --report <tmp>/r.md --json
```

**Captured output / artifact**
- Exit 1; `<tmp>/r.md` exists.
- First line exactly: `# Conformance report: Netflix HD ProRes (approx.) v1.0`.
- Contains `- **Verdict:** ❌ NON-CONFORMANT` and
  `- **Counts:** 3 pass / 6 fail / 0 unknown`.
- Contains a `## Results` heading and the table header row
  `| Requirement | Status | Expected | Actual | Detail |`.
- Contains a `## Suggested fixes` section with **exactly 6** fenced ```` ```ffmpeg ````
  code blocks (one per must failure).

**Verdict: PASS** — all criteria hold.

---

## S11 — unknown spec -> usage error (exit 2)

**Command**
```bash
conforma check examples/probe_netflix_pass.json --spec does-not-exist --json
```

**Captured output (exit 2, single JSON object)**
```json
{"error": "unknown spec 'does-not-exist': not a shipped preset (ebu-broadcast, netflix-hd) and not a readable file"}
```
- Exit code **2** (distinct from 0/1 verdicts). The object's only key is `error`;
  its message indicates the name is not a shipped preset and lists the available
  presets (contains `netflix-hd` and `ebu-broadcast`). No verdict keys
  (`conformant`, `counts`, `results`) present.

**Verdict: PASS** — all criteria hold.

---

## S12 — unknown rule key -> authoring error (exit 2)

**Setup (temp file written by the test)** — `bad.yaml` whose single requirement
uses the unimplemented rule key `not_a_real_rule`.

**Command**
```bash
conforma show <tmp>/bad.yaml --json
```

**Captured output (exit 2, single JSON object)**
```json
{"error": "requirements[0] has unknown key 'not_a_real_rule'. Known rule keys: audio_channels, audio_codec, audio_sample_rate, bit_depth, container, frame_rate, resolution, scan_type, video_codec."}
```
- Exit code **2**; single `{"error": ...}` object; message names the offending key
  `not_a_real_rule` and enumerates all 9 known rule keys (an unknown key is
  rejected as an authoring error, never silently treated as a pass).

**Verdict: PASS** — all criteria hold.

---

## AI-discipline confirmation

No scenario adds, requires, or permits a new model call. Verdicts
(`conformant`, every `status`, every `counts` tally) come from the deterministic
pure functions in `conforma.rules` / `conforma.sequence.rules`. The only model
involvement (S9) is exercised exclusively via `replykit.ScriptedModel` and is
asserted *negatively* — a deliberately wrong model role cannot alter the
deterministic verdict; the model may only narrate (`llm_summary`) or fill a genuine
`role="unknown"` gap.
