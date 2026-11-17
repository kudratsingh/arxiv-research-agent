"""Prospective, opt-in D5 authoring guidance; no producer imports this module.

Examples are invented instructional fixtures, not provider observations or labels.
"""

GUIDANCE_VERSION = "d5-quality-guidance-v20.1"

_COMMON = """Write one independently testable finding per claim. Split independently true or false benchmark numbers and comparator outcomes. Repeat each finding's study scope, comparator, metric and conditions, or explicitly say which are not reported; do not infer missing definitions. Keep a coherent causal or procedural relationship together when it expresses one finding; do not fragment steps merely to satisfy a checker. Cite evidence for the whole claim and check every reference against the current response. Preserve qualifications and requested-part priority. Explain available abstract-level content usefully and identify specific missing methods without inventing them.

Qualitative method comparisons can be supported without a shared benchmark. Performance comparisons require compatible tasks, metrics, comparators and conditions. For comparison-only evidence gaps, retain separately cited source notes where policy permits; do not turn a performance gap into blanket abstention. Context references cannot establish an answer to a comparison. Mark answered only with actual answer claim IDs and no gaps; partial needs answer IDs and genuine remaining gaps. Required missing application context requires full abstention with no claims or claim references. Check all prose, coverage, atomicity, support, qualifications and priority under the existing contract; never weaken abstention rules."""

_REPAIR = """Use the one permitted repair only where the governing policy allows it, then recheck the complete current response. Address the checker's specific findings without fabricating evidence, suppressing genuine gaps, or treating instructions as proof of compliance. No additional repair or recheck is authorized by this guidance."""


def guidance(purpose: str) -> str:
    """Return immutable instructional text for the draft or repair phase."""
    if purpose == "draft":
        return _COMMON
    if purpose == "repair":
        return _COMMON + "\n\n" + _REPAIR
    raise ValueError("purpose must be draft or repair")


# Labels and excerpts are deliberately synthetic; these are not gold judgments.
SYNTHETIC_EXAMPLES = (
    {
        "label": "separate_comparators",
        "source": "In Task A, method M improved accuracy by 8 percentage points over baseline B and by 5 percentage points over baseline C on the held-out set.",
        "claims": (
            {
                "text": "On Task A's held-out set, M scored 8 percentage points higher accuracy than B.",
                "handles": ["u1"],
                "required_scope": "abstract",
            },
            {
                "text": "On Task A's held-out set, M scored 5 percentage points higher accuracy than C.",
                "handles": ["u1"],
                "required_scope": "abstract",
            },
        ),
    },
    {
        "label": "coherent_process",
        "source": "The method reads a document and uses the returned text to select a response.",
        "claims": (
            {
                "text": "The method reads a document and uses the returned text to select a response.",
                "handles": ["u2"],
                "required_scope": "abstract",
            },
        ),
    },
)
