"""The optional replykit layer over the deterministic sequence report.

Verdicts are computed deterministically by :mod:`conforma.sequence.rules`. This
module adds the two — and only two — things genuine model judgment is good for:

1. :func:`infer_ambiguous_roles` — for audio tracks the deterministic extractor
   left ``role="unknown"``, ask the model to classify each from its name + clip
   names (fuzzy NL judgment a keyword list cannot fully encode, e.g. a track
   named ``"REF 2pop temp v3"`` vs ``"Stem A"``). Results merge back as role
   *hints* that the rules consume — but the deterministic keyword match always
   wins when it fired, so the model can only fill genuine gaps.
2. :func:`explain_sequence_report` — a human-readable audit narrative over the
   already-computed deterministic verdict, grounded by a read-only
   :class:`replykit.ToolRegistry` (``get_result`` / ``describe_track``) so the
   model can only restate facts, never change a verdict.

:meth:`SequenceConformanceAgent.check` returns a fully deterministic
:class:`SequenceReport` when ``model is None`` (the hermetic default the tests and
CLI offline mode use). With a :class:`replykit.ScriptedModel` it adds role hints
plus a narrative. **Verdicts always come from** :mod:`conforma.sequence.rules`.
"""

from __future__ import annotations

from dataclasses import replace

from replykit import Agent, Model, ToolRegistry

from .delivery_spec import DeliverySpec
from .models import SequenceLayout, SequenceReport, TrackInfo
from .rules import check_all_sequence

#: The role labels the model is allowed to assign for an ambiguous track.
_ALLOWED_ROLES = ("reference", "me", "dialogue", "music", "other")


def build_sequence_registry(layout: SequenceLayout, report: SequenceReport) -> ToolRegistry:
    """Build a read-only :class:`replykit.ToolRegistry` grounding the narrative.

    Registers deterministic, side-effect-free tools the agent may call —
    ``get_result(key)`` (read back a deterministic verdict) and
    ``describe_track(name)`` (read a track's facts). The model can therefore only
    relay grounded facts, never fabricate a verdict. Returns the populated
    registry.
    """
    by_key = {r.key: r for r in report.results}
    by_track = {t.name: t for t in layout.tracks}
    registry = ToolRegistry()

    @registry.register
    def get_result(key: str) -> str:
        """Return the deterministic verdict line for a sequence rule key."""
        result = by_key.get(key)
        if result is None:
            return f"{key}: no such rule"
        return f"{result.key}: {result.status} — {result.message}"

    @registry.register
    def describe_track(name: str) -> str:
        """Return a one-line factual description of a track by name."""
        track = by_track.get(name)
        if track is None:
            return f"{name}: no such track"
        return (
            f"{track.name}: {track.kind} track #{track.index}, role={track.role}, "
            f"enabled={track.enabled}, clips={len(track.clips)}, "
            f"duration={track.total_duration_seconds:g}s"
        )

    return registry


def _ambiguous_audio_tracks(layout: SequenceLayout) -> list[TrackInfo]:
    return [t for t in layout.tracks if t.kind == "audio" and t.role == "unknown"]


def _parse_role_answer(answer: str) -> str:
    """Map a model's free-text role answer onto our role vocabulary (or 'unknown')."""
    low = answer.strip().lower()
    for role in _ALLOWED_ROLES:
        if role in low:
            return role
    return "unknown"


def infer_ambiguous_roles(
    layout: SequenceLayout, model: Model, *, max_steps: int = 4
) -> SequenceLayout:
    """Fill ``role="unknown"`` audio tracks via the model; return a new layout.

    For each audio track the deterministic extractor left ``"unknown"``, asks the
    model to classify it from its name + clip names. The result is merged back as
    a role *hint*; deterministic roles are never overwritten (they were already
    non-``"unknown"`` and are skipped). Hermetic when ``model`` is a
    :class:`replykit.ScriptedModel`. Returns a new :class:`SequenceLayout` (the
    input is never mutated).
    """
    ambiguous = _ambiguous_audio_tracks(layout)
    if not ambiguous:
        return layout

    registry = ToolRegistry()  # role inference needs no tools, only judgment
    updated: dict[int, str] = {}
    for track in ambiguous:
        clip_names = [c.name for c in track.clips]
        task = (
            "Classify this audio track of a film/TV delivery timeline into exactly "
            f"one role from {list(_ALLOWED_ROLES)}.\n"
            f"Track name: {track.name!r}\n"
            f"Clip names: {clip_names!r}\n"
            "Reply with just the single role word. 'reference' means a scratch/"
            "temp/WIP/guide stem that must be muted on delivery."
        )
        agent = Agent(model, registry, max_steps=max_steps)
        answer = agent.run(task).answer
        role = _parse_role_answer(answer)
        if role != "unknown":
            updated[id(track)] = role

    if not updated:
        return layout

    new_tracks = [replace(t, role=updated[id(t)]) if id(t) in updated else t for t in layout.tracks]
    return replace(layout, tracks=new_tracks)


def _summarize_results(report: SequenceReport) -> str:
    lines = []
    for r in report.results:
        lines.append(f"- {r.key}: {r.status} (expected {r.expected!r}, actual {r.actual!r})")
    return "\n".join(lines)


def explain_sequence_report(
    report: SequenceReport,
    layout: SequenceLayout,
    model: Model,
    *,
    max_steps: int = 6,
) -> str:
    """Produce a natural-language audit narrative of a sequence report.

    Wires ``model`` and :func:`build_sequence_registry` into a
    :class:`replykit.Agent`, runs it over a prompt describing the deterministic
    results, and returns the agent's final-answer narrative. Pure read-over of an
    already-computed report: it never changes a verdict. Hermetic when ``model``
    is a :class:`replykit.ScriptedModel`.
    """
    registry = build_sequence_registry(layout, report)
    agent = Agent(model, registry, max_steps=max_steps)
    verdict = "CONFORMANT" if report.conformant else "NON-CONFORMANT"
    task = (
        f"A delivery timeline was checked against the sequence spec "
        f"{report.spec_name!r} (v{report.spec_version}). The deterministic verdict "
        f"is {verdict}. Per-rule results:\n"
        f"{_summarize_results(report)}\n\n"
        "Write a short, plain-language audit summary of the outcome. You may call "
        "get_result(key) and describe_track(name) to ground any detail; do not "
        "invent results or change the verdict."
    )
    return agent.run(task).answer


class SequenceConformanceAgent:
    """The one-call entry point: spec + layout -> sequence report.

    Computes the deterministic report first (always). With no model,
    :meth:`check` returns a fully deterministic :class:`SequenceReport` — the
    hermetic default the tests and the CLI's offline mode use. With a ``model``
    it (1) fills ambiguous audio-track roles via :func:`infer_ambiguous_roles`
    *before* the verdict, so those hints feed the rules, and (2) attaches an LLM
    audit narrative via :func:`explain_sequence_report`. Verdicts are always from
    :mod:`conforma.sequence.rules`.
    """

    def __init__(self, model: Model | None = None, *, max_steps: int = 6) -> None:
        self.model = model
        self.max_steps = max_steps

    def check(self, spec: DeliverySpec, layout: SequenceLayout) -> SequenceReport:
        """Run the deterministic pre-checks and (optionally) the model layer.

        Returns a :class:`SequenceReport` whose verdicts are always deterministic.
        """
        effective_layout = layout
        if self.model is not None:
            # Fuzzy role hints feed the deterministic rules; they never override a
            # role the keyword matcher already resolved.
            effective_layout = infer_ambiguous_roles(layout, self.model, max_steps=self.max_steps)

        results = check_all_sequence(effective_layout, spec)
        report = SequenceReport(
            spec_name=spec.name,
            spec_version=spec.version,
            sequence_source=effective_layout.source,
            results=results,
        )

        if self.model is None:
            return report

        summary = explain_sequence_report(
            report, effective_layout, self.model, max_steps=self.max_steps
        )
        return replace(report, llm_summary=summary)
