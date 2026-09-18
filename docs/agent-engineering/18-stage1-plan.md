# Stage-1 calibration plan

This artifact is the predeclared observation plan for the first funded
calibration tranche. It is deliberately small and is written before any
candidate result is inspected.

The three queries are fixed by shape: `straightforward-literature-overview`
is straightforward, `comparative-methods-tradeoff` is comparative, and
`likely-revision-open-question` is expected to cause at least one planner
revision. The exact registry query text and revision are sealed in the Stage-1
campaign manifest.

For each query and arm, Stage 1 reports:

- input and output tokens per role (min, median, and max);
- revisions per episode;
- judge JSON parse success and the null reason when parsing fails;
- the definition and numerator used for `claim_count`;
- surname-year citation collisions; and
- abstract-only reader fallbacks.

The report retains episode ids, retrieval timestamps, resolved source ids,
model ids, and denominators. These observations feed the tranche 2a checkpoint
and the query-first variance estimate; they do not authorize a live run.
