"""Judge-calibration schemas, fixtures and metrics — P0-WO10.

This package is the *design and measurement* half of AE-004. It defines
what a human calibration label is, how disagreement is preserved and
adjudicated, how a judge is blinded, how many items each task slice
needs, what "agreement" is allowed to mean in a report, and when a judge
may be used as a release gate. It does not run a judge, call a provider,
or start a labeling campaign, and nothing in it may.

The protocol this package implements is
``docs/agent-engineering/14-judge-calibration-protocol.md``.

Four rules shape every module here:

1. **A model verdict is an instrument reading, not a label.**
   :class:`~src.calibration.labels.CalibrationLabel` refuses an
   annotator of kind ``model`` outright; a judge's answer is a
   :class:`~src.calibration.labels.JudgeVerdict`, a different type with
   no annotator field at all. There is no way to spell "a model
   produced ground truth" in this vocabulary.
2. **Disagreement is retained.**
   :class:`~src.calibration.labels.AdjudicationRecord` carries every
   individual decision plus the adjudicated outcome and the rule that
   produced it. A consensus value never overwrites the decisions it came
   from, and an item whose annotators disagree with no adjudication has
   *no* resolved decision rather than a quietly chosen one.
3. **Every rate is published with its denominator and an interval**,
   both from :mod:`src.eval.stats` (ADR 0071) rather than a second
   implementation. ``docs/eval.md`` already fixed the reporting form for
   this measurement before it existed: φ/MCC with both positive rates,
   never raw agreement alone, and an explicit statement of how
   abstentions were counted. :mod:`src.calibration.metrics` enforces all
   three.
4. **Zero spend, zero network, zero clock.** Nothing here imports
   ``src.llm`` or opens a socket, and every timestamp is data supplied
   by a caller. :mod:`src.calibration.suite` imports the *rubric
   versions* the current judges publish so a calibration set can name
   the instrument it was authored against; it never calls one.
"""

from src.calibration.blinding import (
    HIDDEN_FROM_JUDGE,
    BlindingPlan,
    PairOrder,
    Presentation,
    PresentationAssignment,
    assign_presentations,
    blind_item_id,
    leaked_identity_terms,
)
from src.calibration.labels import (
    GROUND_TRUTH_ANNOTATOR_KINDS,
    HUMAN_ANNOTATOR_KINDS,
    AdjudicationRecord,
    AdjudicationRule,
    Annotator,
    AnnotatorKind,
    CalibrationLabel,
    Confidence,
    JudgeVerdict,
    LabelledItem,
    LabelType,
    binary_outcome,
    decision_vocabulary,
    registry_label_records,
)
from src.calibration.metrics import (
    DEFAULT_THRESHOLDS,
    INTEGRITY_VIOLATION_CLASSES,
    AbstentionPolicy,
    AgreementReport,
    CalibrationReport,
    ConfusionCounts,
    ErrorRates,
    GateDecision,
    GateState,
    IntegrityFinding,
    PositionBias,
    SliceCoverage,
    UsabilityThresholds,
    agreement,
    build_report,
    confusion,
    decide,
    error_rates,
    phi_coefficient,
    position_bias,
    rate_with_interval,
    report_lines,
    slice_coverage,
)
from src.calibration.sampling import (
    FAILURE_CLASSES,
    TASK_SLICES,
    NoiseFloor,
    SamplingPlan,
    SliceRequirement,
    SliceSpec,
    items_for_precision,
    items_to_bound_below,
    noise_floor,
    slice_requirements,
    standard_plan,
)

__all__ = [
    "DEFAULT_THRESHOLDS",
    "FAILURE_CLASSES",
    "GROUND_TRUTH_ANNOTATOR_KINDS",
    "HIDDEN_FROM_JUDGE",
    "HUMAN_ANNOTATOR_KINDS",
    "INTEGRITY_VIOLATION_CLASSES",
    "TASK_SLICES",
    "AbstentionPolicy",
    "AdjudicationRecord",
    "AdjudicationRule",
    "AgreementReport",
    "Annotator",
    "AnnotatorKind",
    "BlindingPlan",
    "CalibrationLabel",
    "CalibrationReport",
    "Confidence",
    "ConfusionCounts",
    "ErrorRates",
    "GateDecision",
    "GateState",
    "IntegrityFinding",
    "JudgeVerdict",
    "LabelType",
    "LabelledItem",
    "NoiseFloor",
    "PairOrder",
    "PositionBias",
    "Presentation",
    "PresentationAssignment",
    "SamplingPlan",
    "SliceCoverage",
    "SliceRequirement",
    "SliceSpec",
    "UsabilityThresholds",
    "agreement",
    "assign_presentations",
    "binary_outcome",
    "blind_item_id",
    "build_report",
    "confusion",
    "decide",
    "decision_vocabulary",
    "error_rates",
    "items_for_precision",
    "items_to_bound_below",
    "leaked_identity_terms",
    "noise_floor",
    "phi_coefficient",
    "position_bias",
    "rate_with_interval",
    "registry_label_records",
    "report_lines",
    "slice_coverage",
    "slice_requirements",
    "standard_plan",
]
