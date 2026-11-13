# Product direction

## Purpose and audience

The owner is an ML student and researcher who wants to follow frontier systems
and techniques, understand their assumptions and relationships, reproduce
useful parts, and form better research questions. Interests may extend into
any field of study. The app should be useful every morning and sustain a
research thread across weeks.

The daily loop is **notice → understand → connect → test → retain**. Success
means a useful reading decision, a source-backed insight or a concrete next
experiment. Reading more cards is not the objective.

Owner decisions on 2026-11-02: daily briefing plus guided deep dives lead;
operation is local first; paid services require separate approval. Keep the
existing application and its evidence conventions. No public launch, team
workspace, course business or training pipeline is part of the first release.

## Needs the application must satisfy

| Need | Product response | Important boundary |
|---|---|---|
| Know what changed since my last visit | Date-window briefing, update clusters, versions, new code/weights and corrections | Distinguish publication, update, discovery and last-check time |
| Find work relevant to my goals | Topic hierarchy, free-text questions, seed papers, methods, authors/labs, exclusions and relevance feedback | Explain why an item matched; popularity is not quality |
| Learn material above my current level | Adjustable explanation depth, prerequisites, equations and worked examples linked to the passage | Source claims and instructional examples are labelled separately |
| Judge a frontier result | Claimed result, experimental setting, assumptions, baselines, limitations and missing evidence | Author-reported numbers are not independently reproduced results |
| Understand relationships | Compare to saved work, typed source-backed links and contextual relationship lists | Semantic similarity is not a demonstrated scientific relationship |
| Build what I read | Code/data/model links, reproducibility checklist and a minimal experiment proposal | Do not promise hardware feasibility when requirements are unknown |
| Develop ideas | Link hypotheses to observations, search related work, state disconfirming tests | Novelty is a bounded search outcome, never an automatic guarantee |
| Continue tomorrow | Persistent questions, last-read anchor, saved annotations and next steps | Chat history alone is not research memory |
| Avoid being buried | Briefing limits, read-later, snooze, catch-up, daily/weekly schedules, quiet hours | A skipped day does not create an endless backlog |
| Keep control of cost and data | Metadata-first mode, bounded generation, local storage/export and explicit source requests | A free source API can still have keys, quotas and terms |

## Strong features that make this specific to research

### A briefing that remembers your question

An interest may be a field such as machine learning, or a research question
such as “How can I evaluate retrieval quality with limited compute?” Connect
items to that question and to the papers already saved. Show which evidence
would change the user's present understanding, rather than repeatedly
introducing the same topic. A profile supports several focused lenses without
mixing project goals, general curiosity and prerequisites into one score.

### Changes since the earlier paper

Group the paper, subsequent versions, official code, model release and primary
announcement. One cluster may say “implementation released; paper already
saved.” Preserve each source's authorship and evidence status. Mark affected
summaries stale when their input version changes. Regenerate only under an
enabled, approved budget policy; keep earlier versions accessible and mark
them superseded once a replacement exists.

### An assumption ledger

For a source-backed result record: what must be true, where that assumption
appears, what the experiment actually varied, and what has not been tested.
The reader can pin an assumption as a question and later attach confirming or
contradicting evidence. A comparison can then say “different data regime”
instead of asserting that one method beats another on incompatible evidence.

### From paper to a small build

Offer a build brief with the smallest test of the idea: goal, baseline, dataset
or synthetic task, independent variables, metrics, expected failure, hardware
requirements and a stopping condition. The user supplies available hardware
and time; absent values remain unknown. A proposal is saved for execution in
the user's normal development workflow. Autonomous code execution is outside
the first release.

### A question and idea notebook

Keep questions, source-backed observations, derived inferences, hypotheses and
experiment outcomes as distinct records. An idea carries its parent sources,
possible prior work, rationale and falsifying test. Mark a novelty check with
the queries, sources, dates and limitations of the search. Do not award
fabricated “novelty scores.”

### Useful bridges between fields

Reserve a small, adjustable exploration allocation for adjacent areas. For
example, connect an ML interest to scientific measurement or optimization
only with an explained mechanism and supporting sources. The user can turn
exploration down or off and mark a bridge useful, unrelated or too advanced.
Never claim that every selectable field has adequate live coverage.

## Scope by horizon

| Horizon | Complete behavior |
|---|---|
| First owner preview | One coherent fixture flow: choose interests → Today → item → reader → save question → return next day; desktop and mobile |
| First daily local release | Real bounded arXiv/RSS intake; dedup/versioning; transparent ranking; saved library and notes; local schedules/catch-up; useful source-excerpt briefing without model calls |
| Approved generated-analysis release | Cached grounded summaries; selected-item guided deep dive; source citations, independent source retention, null/uncertainty handling, version invalidation and hard generation budgets |
| Research continuity | Project-linked questions, comparisons, assumptions, weekly synthesis and build briefs; citation export/import |
| Broader expansion | Additional scholarly fields/adapters, repository/model updates, richer relation maps, optional notification delivery and an optional always-on private deployment |

The broad topic picker and manual URL/identifier entry belong early. Activating
dozens of polling connectors and expensive deep dives for every topic does not.

## Recommendations for personalization

Use transparent deterministic ranking first. Filter exclusions and source
access; deduplicate; then combine explicit interest relevance, new information
relative to the library, freshness, project match, diversity and user feedback.
Keep component explanations. Use embeddings as a recall signal after a small
labelled relevance benchmark; do not train a recommender for this first user.

Offer feedback reasons: off-topic, already known, too introductory, too
advanced, weak source, duplicate, more like this, less like this. Undo is
available. Manual interest choices take priority over inferred preferences.
Reading behavior is noisy: opening an item must not silently redefine the
user's field of study. Export and reset inferred preferences separately.

Proposed starting limits are 3 highlighted changes, up to 12 additional
clusters, one suggested deep dive and a small adjacent-work section. These
are design hypotheses to test during daily use, not evidence-backed optimal
numbers. Let the owner choose a 5-, 15- or 45-minute reading mode.

## How this changes the earlier plans

The new direction brings the adopted research radar and paper-reading companion
to the front. Reuse the old research and learning engines where their behavior
fits. The flagship course, public publication, educational pilot and W20
engagement gate remain historical/product options rather than dependencies.
Keep the historical evaluation record; fix the measurement defects necessary
for generated-analysis claims. Broader RL, model post-training and autonomous
self-modification remain deferred. The implementing agent should document this
sequencing change in an ADR without rewriting older evidence reports.
