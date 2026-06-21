"""conforma — a delivery-spec compliance agent for post-production media.

``conforma`` ingests a delivery spec (YAML) plus a media file's probe data
(``ffprobe -print_format json`` or MediaInfo JSON), runs **deterministic** rule
pre-checks (resolution, frame rate, codec, bit depth, audio config, container),
and then drives a :mod:`replykit` :class:`~replykit.Agent` to produce a
pass/fail conformance report per requirement — each failure carrying a suggested
``ffmpeg`` fix command.

The deterministic core (everything except :mod:`conforma.agent`) imports with
**zero** LLM calls and is fully exercisable from committed fixture JSON: no real
``ffmpeg``, ``ffprobe``, or media files are required to run the checks or the
test suite. Shelling out to ``ffprobe`` is strictly optional (:func:`probe_media`)
and never required.

This is the single import surface for the v0.1 public contract.
"""

from __future__ import annotations

from .agent import (
    ConformanceAgent,
    build_fix_registry,
    explain_report,
)
from .errors import (
    ConformaError,
    ProbeError,
    SpecError,
)
from .fixes import (
    suggest_fix,
)
from .models import (
    AudioProfile,
    CheckStatus,
    ConformanceReport,
    MediaProfile,
    Requirement,
    RuleResult,
    Spec,
    VideoProfile,
)
from .probe import (
    ProbeSource,
    ffprobe_available,
    load_probe,
    normalize_probe,
    probe_media,
)
from .report import (
    render_report,
    render_report_markdown,
    report_to_dict,
)
from .rules import (
    RULES,
    Rule,
    check_all,
    check_requirement,
)
from .spec import (
    PRESETS,
    list_presets,
    load_preset,
    load_spec,
    parse_spec,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # errors
    "ConformaError",
    "SpecError",
    "ProbeError",
    # models
    "Spec",
    "Requirement",
    "MediaProfile",
    "VideoProfile",
    "AudioProfile",
    "RuleResult",
    "ConformanceReport",
    "CheckStatus",
    # spec
    "load_spec",
    "parse_spec",
    "load_preset",
    "list_presets",
    "PRESETS",
    # probe
    "load_probe",
    "normalize_probe",
    "probe_media",
    "ffprobe_available",
    "ProbeSource",
    # rules
    "Rule",
    "RULES",
    "check_requirement",
    "check_all",
    # fixes
    "suggest_fix",
    # agent
    "ConformanceAgent",
    "build_fix_registry",
    "explain_report",
    # report
    "render_report",
    "render_report_markdown",
    "report_to_dict",
]
