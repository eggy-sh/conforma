# Contributing to conforma

Thanks for helping improve conforma. This project is part of the
[Post-Production Agent Kit](https://github.com/eggy-sh) and is built on the
[`replykit`](https://github.com/eggy-sh/replykit) engine.

## Ground rules

1. **The suite is hermetic.** No test may touch the network, a real LLM, real
   `ffmpeg`/`ffprobe`, or a real media file. Probe data comes from committed
   JSON under `tests/fixtures/`; any model is a `replykit.ScriptedModel`. The one
   function that shells out (`probe_media`) is tested by monkeypatching the
   subprocess boundary.
2. **Verdicts are deterministic.** The pass/fail decision lives entirely in
   `conforma.rules` and must be reproducible from a fixture. The agent layer may
   narrate or attach a fix, but must never change a verdict.
3. **Fixes are grounded.** ffmpeg fix commands come from
   `conforma.fixes.suggest_fix` only — the LLM cannot invent one.

## Development setup

```bash
uv venv && uv pip install -e '/path/to/replykit' && uv pip install -e '.[dev]'
# or, without uv:
python3 -m venv .venv && .venv/bin/pip install -e '/path/to/replykit' \
  && .venv/bin/pip install -e '.[dev]'
```

Confirm the install:

```bash
.venv/bin/python -c "import replykit, conforma; print(conforma.__version__)"
```

## Checks before a PR

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest --cov=conforma --cov-report=term-missing
```

CI runs ruff + pytest on Python 3.11 and 3.12. Coverage must stay at or above
the `fail_under` threshold in `pyproject.toml`.

## Adding a delivery-spec rule

1. Implement a pure `(Requirement, MediaProfile) -> RuleResult` function in
   `conforma/rules.py` and register it in `RULES`.
2. Add a remediation branch in `conforma/fixes.py` keyed on the requirement key.
3. Add unit tests (pass / fail / UNKNOWN) driven by fixtures.
4. If it is broadly useful, reference it in a preset under `conforma/presets/`.

## Adding or changing a preset

Presets are illustrative approximations, **not** official studio documents. Keep
the disclaimer comment at the top of each preset YAML and add a fixture that both
passes and fails it.
