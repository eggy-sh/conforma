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
from .sequence.agent import (
    SequenceConformanceAgent,
    build_sequence_registry,
    explain_sequence_report,
    infer_ambiguous_roles,
)
from .sequence.delivery_spec import (
    SEQ_PRESETS,
    DeliverySpec,
    list_seq_presets,
    load_delivery_spec,
    load_seq_preset,
    parse_delivery_spec,
)
from .sequence.errors import (
    SequenceError,
    SequenceSpecError,
)
from .sequence.extract import (
    ROLE_KEYWORDS,
    extract_layout,
    find_slate,
    infer_role_deterministic,
)
from .sequence.fix import (
    apply_fixes,
    fix_sequence,
)
from .sequence.models import (
    ClipInfo,
    SeqCheckStatus,
    SeqRuleResult,
    SequenceLayout,
    SequenceReport,
    TrackInfo,
)
from .sequence.otio_io import (
    SUFFIX_ADAPTERS,
    adapter_available,
    available_adapters,
    read_timeline,
    write_timeline,
)
from .sequence.report import (
    render_sequence_report,
    render_sequence_report_markdown,
    sequence_report_to_dict,
)
from .sequence.rules import (
    SEQ_RULES,
    check_all_sequence,
    check_audio_track_count,
    check_reference_audio_muted,
    check_slate_duration,
    check_video_track_count,
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
    # --- sequence conformance (conform_validator) ---
    # errors
    "SequenceError",
    "SequenceSpecError",
    # models
    "ClipInfo",
    "TrackInfo",
    "SequenceLayout",
    "SeqCheckStatus",
    "SeqRuleResult",
    "SequenceReport",
    # otio_io
    "read_timeline",
    "write_timeline",
    "adapter_available",
    "available_adapters",
    "SUFFIX_ADAPTERS",
    # extract
    "extract_layout",
    "infer_role_deterministic",
    "find_slate",
    "ROLE_KEYWORDS",
    # delivery spec
    "DeliverySpec",
    "parse_delivery_spec",
    "load_delivery_spec",
    "load_seq_preset",
    "list_seq_presets",
    "SEQ_PRESETS",
    # rules
    "check_all_sequence",
    "check_slate_duration",
    "check_reference_audio_muted",
    "check_video_track_count",
    "check_audio_track_count",
    "SEQ_RULES",
    # report
    "sequence_report_to_dict",
    "render_sequence_report",
    "render_sequence_report_markdown",
    # fix
    "apply_fixes",
    "fix_sequence",
    # agent
    "SequenceConformanceAgent",
    "build_sequence_registry",
    "explain_sequence_report",
    "infer_ambiguous_roles",
]
