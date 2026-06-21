"""The replykit-powered layer over the deterministic conformance report.

Verdicts are computed deterministically by :mod:`conforma.rules`. This module
adds the value an LLM is actually good at: a clear natural-language narrative of
what failed and why, and a tool-grounded fix command per failure. It wires a
:class:`replykit.Agent` to a :class:`replykit.ToolRegistry` whose only tools are
deterministic conforma functions, so the model can *surface* a fix or restate a
result but can never fabricate a verdict or an unverified ffmpeg command.

The agent is **optional**: :func:`ConformanceAgent.check` falls back to the
deterministic report (with fixes from :func:`conforma.fixes.suggest_fix`) when no
model is supplied, which is exactly the hermetic path tests and CI exercise. When
a model *is* supplied it may be a :class:`replykit.ScriptedModel` (hermetic) or a
real provider adapter.
"""

from __future__ import annotations

from dataclasses import replace

from replykit import Agent, Model, ToolRegistry

from . import fixes
from .models import ConformanceReport, MediaProfile, RuleResult, Spec
from .rules import check_all


def build_fix_registry(
    report: ConformanceReport,
    *,
    input_path: str = "INPUT",
    output_path: str = "OUTPUT",
) -> ToolRegistry:
    """Build a :class:`replykit.ToolRegistry` exposing conforma's safe tools.

    Registers deterministic, side-effect-free tools the agent may call — e.g.
    ``suggest_fix(key)`` (look up the committed ffmpeg remediation for a failing
    requirement) and ``get_result(key)`` (read back a deterministic verdict). The
    model can therefore only relay grounded facts, never invent a verdict or
    command. Returns the populated registry.
    """
    by_key = {r.key: r for r in report.results}
    registry = ToolRegistry()

    @registry.register
    def suggest_fix(key: str) -> str:
        """Return the deterministic ffmpeg fix command for a failing requirement key."""
        result = by_key.get(key)
        if result is None:
            return ""
        # Prefer the already-computed command; otherwise recompute deterministically.
        if result.fix_command:
            return result.fix_command
        return fixes.suggest_fix(result, input_path=input_path, output_path=output_path)

    @registry.register
    def get_result(key: str) -> str:
        """Return the deterministic verdict line for a requirement key."""
        result = by_key.get(key)
        if result is None:
            return f"{key}: no such requirement"
        return f"{result.key}: {result.status} — {result.message}"

    return registry


def _summarize_results(report: ConformanceReport) -> str:
    lines = []
    for r in report.results:
        line = f"- {r.key}: {r.status} (expected {r.expected!r}, actual {r.actual!r})"
        lines.append(line)
    return "\n".join(lines)


def explain_report(
    report: ConformanceReport,
    model: Model,
    *,
    max_steps: int = 6,
) -> str:
    """Produce a natural-language summary of a report via a replykit agent.

    Wires ``model`` and :func:`build_fix_registry` into a :class:`replykit.Agent`,
    runs it over a prompt describing the deterministic results, and returns the
    agent's final-answer narrative. Pure read-over of an already-computed report:
    it never changes a verdict. Hermetic when ``model`` is a
    :class:`replykit.ScriptedModel`.
    """
    registry = build_fix_registry(report)
    agent = Agent(model, registry, max_steps=max_steps)
    verdict = "CONFORMANT" if report.conformant else "NON-CONFORMANT"
    task = (
        f"A media file was checked against the delivery spec "
        f"{report.spec_name!r} (v{report.spec_version}). The deterministic "
        f"verdict is {verdict}. Per-requirement results:\n"
        f"{_summarize_results(report)}\n\n"
        "Write a short, plain-language summary of the conformance outcome. For "
        "any failing requirement, call the suggest_fix tool with its key to get "
        "the grounded ffmpeg fix; do not invent commands or change the verdict."
    )
    result = agent.run(task)
    return result.answer


class ConformanceAgent:
    """The one-call entry point: spec + media profile -> conformance report.

    Computes the deterministic report first (always), then — if a ``model`` was
    supplied — enriches it with an LLM narrative via :func:`explain_report` and
    fix commands grounded in :func:`conforma.fixes.suggest_fix`. With no model,
    :meth:`check` returns a fully populated deterministic report (fixes included),
    which is the hermetic default used by tests and the CLI's offline mode.
    """

    def __init__(
        self,
        model: Model | None = None,
        *,
        max_steps: int = 6,
    ) -> None:
        self.model = model
        self.max_steps = max_steps

    def check(
        self,
        spec: Spec,
        profile: MediaProfile,
        *,
        input_path: str = "INPUT",
        output_path: str = "OUTPUT",
    ) -> ConformanceReport:
        """Run pre-checks, attach fixes, and (optionally) an LLM summary.

        Returns a :class:`~conforma.models.ConformanceReport` whose verdicts are
        always deterministic. ``input_path`` / ``output_path`` flow into the
        generated ffmpeg fix commands.
        """
        raw_results = check_all(spec.requirements, profile)
        results: list[RuleResult] = []
        for result in raw_results:
            fix = fixes.suggest_fix(result, input_path=input_path, output_path=output_path)
            results.append(replace(result, fix_command=fix) if fix else result)

        report = ConformanceReport(
            spec_name=spec.name,
            spec_version=spec.version,
            media_source=profile.source,
            results=results,
        )

        if self.model is None:
            return report

        summary = explain_report(report, self.model, max_steps=self.max_steps)
        return replace(report, llm_summary=summary)
