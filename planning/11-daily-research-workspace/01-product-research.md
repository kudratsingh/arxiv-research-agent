# Daily research workspace product research

Research date: **2026-11-02**. Product recommendations for Kudrat's personal
research workflow. The observations below come from public official product
documentation and one research paper; authenticated product behavior was not
tested. Vendor descriptions establish advertised workflows, not their accuracy
or their effectiveness for this user.

The strongest direction is a continuous loop from **what changed** to **what
it means for my work**, then **understand**, **try**, and **record what I
learned**. A daily list of AI summaries would cover only the first step.

**Owner choices received during planning:** the first version leads with a
daily briefing and guided deep dives, and operates locally. Paid services
require separate approval. The daily briefing must therefore remain useful
with metadata, attributed source abstracts/excerpts, transparent matching and
durable reading actions while paid generation is disabled. An unavailable AI
summary must be shown as unavailable; source abstracts are not generated
summaries. Local reading, saved notes and question continuity must work without
a paid call. Scheduled collection can catch up when the machine wakes; daily
delivery while it sleeps is not promised.

## Research observations and their implications

| Observed workflow | Evidence checked | Design implication for this project |
|---|---|---|
| Semantic Scholar builds Research Feeds from saved-paper folders, refreshes recommendations daily, and accepts positive saves and explicit negative relevance feedback | [Official Research Feeds FAQ](https://webflow.semanticscholar.org/faq/create-research-feeds), accessed 2026-11-02 | Onboarding needs seed papers and exclusions in addition to topics. Let one saved project collection train one watch. Make relevance feedback understandable and reversible |
| Elicit's current Alerts URL presents **Routines**: describe recurring research in natural language, review proposed instructions/schedule, inspect sources and sessions, refine or pause, and update an existing artifact | [Official Routines page](https://elicit.com/solutions/alerts), accessed 2026-11-02; older indexed Alerts text differs from the current page | Recurring agent research is already a product category. A differentiated experience here needs personal research continuity, learning and implementation support; it cannot rely on scheduling alone |
| ResearchRabbit supports exploration of similar, earlier and later work; research/author networks; iterative searches from chosen papers; collections and notes | [Official October 2025 release guide](https://learn.researchrabbit.ai/en/articles/12440130-welcome-to-the-new-researchrabbit), accessed 2026-11-02 | Discovery should expand from papers the user has actually chosen. Offer explicit relationship types and a useful list before a large graph |
| Litmaps monitors saved searches/maps and retains past results; its help page describes configurable frequency/filters for eligible users | [Official Monitor guide](https://docs.litmaps.com/en/articles/9126249-monitor-get-alerts-for-important-research), dated 2025-02-26, accessed 2026-11-02 | A monitor is a persistent research question with a history, not just a transient notification. Support pause, edit, backfill and inspection of earlier digests |
| Feedly groups sources into feeds/boards, supports relevance and noise controls, deduplication, notes and summaries | [Official getting-started guide](https://docs.feedly.com/article/523-getting-started-with-feedly), updated 2025-10-20, accessed 2026-11-02 | News needs source management and negative controls. Explain source coverage and allow temporary muting, not only an opaque recommendation model |
| Zotero supports continuously updated saved searches and annotations that link back to a PDF page and citation | [Saved searches](https://www.zotero.org/support/searching), [PDF reader and note editor](https://www.zotero.org/support/pdf_reader), accessed 2026-11-02 | Notes and reading decisions should be durable, portable and traceable to source locations. Export or integrate with existing libraries rather than make the user's research depend on one app |
| Hugging Face Paper Pages connect papers with models, datasets and Spaces; links from repository cards create paper associations | [Official Paper Pages documentation](https://huggingface.co/docs/hub/paper-pages), accessed 2026-11-02 | A paper should expose implementation artifacts and their provenance. An association establishes a link, not reproduction quality or verified hardware requirements |

The research prototype **PaperWeaver** contextualized recommended papers
against users' collected papers. Its CHI 2024 paper reports a 15-participant
study with better relevance understanding and more confident triage than its
chosen related-work baseline. That is limited evidence for making connections
explicit; it does not establish factual accuracy, long-term retention or the
effectiveness of this proposed app. [Original paper, v2 2024-05-09](https://arxiv.org/abs/2403.02939).

## The user's jobs to be done

The primary persona is an ML student and researcher who also builds systems.
The product should support five intentions without making the user change
tools or re-explain the same context:

1. **Keep up:** identify a few developments that matter across chosen fields.
2. **Understand:** read the actual paper, prerequisites, mechanism, equations,
   evidence, assumptions and limitations at a chosen depth.
3. **Connect:** relate a new result to prior work, other fields and the user's
   own saved questions or project constraints.
4. **Build:** turn a method into a small feasible experiment, then distinguish
   what was proposed from what was actually run.
5. **Develop ideas:** preserve hypotheses, competing explanations, unknowns and
   discriminating tests instead of producing disposable brainstorms.

The app should answer three recurring questions: **Why am I seeing this? What
should change in my understanding? What can I do next?** It should also make
“nothing important changed” a valid result.

## Daily and weekly workflows

### Ten minute daily briefing

The opening view shows a finite briefing for the user's available time, with a
clear generation time and the last successful collection time for each watch.
An early workshop example used five main items and one adjacent-field
connection. The canonical configurable proposal is now in document 00:
three highlighted changes, up to twelve additional clusters, one suggested
deep dive and a small adjacent-work section. Validate that allowance against
the selected reading time; no item count is claimed to be optimal.

Each main item states the development, the source type, the date/version, its
relation to a saved interest or project, the main caveat and an action. Related
coverage of one announcement is grouped. A preprint, model release, independent
replication, institutional press release and opinion piece remain distinguishable.

The user can save for depth, mark read, dismiss with a reason, snooze the topic,
or attach the item to a research question. Opening an item is not treated as
proof of interest or understanding. The briefing ends with a small “continue
your work” area containing the last unfinished reading question or experiment.

### Forty five minute paper investigation

From one briefing item, the user opens a research desk with source text and
evidence beside the agent's explanation. It restores the reading position,
notes and unresolved questions. Suggested investigations include:

- explain the mechanism and prerequisites at my current level;
- trace this result to the experiment and comparison that supports it;
- identify assumptions and where they fail;
- compare with a paper or method I already saved;
- show the strongest available counterevidence or an untested condition;
- outline the smallest useful implementation for my machine.

The investigation can produce a structured note: question, mechanism, tested
setting, result, limitations, connection to prior work, unresolved questions,
and proposed next action. Each factual element links to the material actually
available. Abstract-only access is visible; it cannot support a claim about
an unseen ablation, equation or result table.

### Weekly synthesis and build loop

At the user's request or approved cadence, the app summarizes changes to saved
research questions: evidence added, claims weakened, unresolved disagreements,
ideas abandoned and experiments worth trying. It includes a few unfinished
threads with a useful next action; it does not turn every missed article into
debt.

An experiment brief records a falsifiable hypothesis, baseline, data, minimal
method, measurements, expected resource envelope, failure interpretation and
stop conditions. The user can attach results later. Generated instructions
remain proposed until a run record or user-supplied evidence exists. The first
release can support this with a durable structured note and export; autonomous
code execution is not necessary to complete this loop.

## Strong product ideas worth building

### Research questions that remain open

An interest such as “efficient transformers” is too broad to guide every
recommendation. Let the user maintain questions such as “Which memory approach
can improve my agent without increasing retrieval latency?” A question carries
constraints, known references, competing approaches and unknowns. A watch
monitors evidence relevant to that question, while a broad field subscription
continues to provide discovery.

The important artifact is a changing answer with provenance and an unresolved
questions list. The agent can propose changing the watch's interpretation;
the user can inspect and accept that change rather than have the target drift.

### An assumptions and evidence comparison

Replace a single “importance” score with a concise evidence profile: what is
claimed, under which conditions, against what baseline, with what compute,
data or implementation access, and what has not been tested. Later versions
can compare these dimensions across papers in a table. A blank cell means
unknown, not failure or success.

For ML, this prevents a headline improvement on a small benchmark from becoming
a blanket architecture recommendation. Across science, it lets population,
measurement method and experimental setting remain attached to a conclusion.

### A personal connection explanation

“Related to your project” should name the relation: shares a mechanism, changes
a constraint, supplies a baseline, offers a reusable artifact, contradicts a
claim, or suggests an analogy. A citation edge proves citation, not agreement.
Embedding proximity suggests similarity, not causation. Agent-inferred
connections need supporting passages or a hypothesis label.

The interface should initially show two or three useful connections with
inspectable evidence. A graph can become a secondary exploration view after
the relationship data is trustworthy.

### A buildability brief

The user's hardware, available time, budget, programming familiarity and goal
should shape implementation suggestions. Distinguish reproducing a headline
result, reproducing one ablation, testing the principle on a toy task, and
using released weights. Show missing licenses, data, weights, environment or
hardware information as missing. A rough compute estimate states its inputs.

This is more useful than a generic “code available” badge: the question is
whether a useful test is feasible for this person.

### An idea ledger with counterchecks

An idea records the observation that motivated it, the proposed mechanism,
closest work found, major assumptions, potential refutation and a small test.
The novelty field should say “not found in the sources searched” with a search
scope and date. It must never certify that an idea is new. The app can ask what
observation would cause the user to abandon or revise it.

Ideas can change status from captured to investigated to experiment planned,
tested or abandoned. Preserve the reason for abandonment; failed ideas are
part of research memory, not items to erase for a cleaner dashboard.

### Catch up without a backlog penalty

After a week away, the app should offer a compact account of meaningful
changes and leave a searchable archive of ordinary arrivals. Persistent urgent
alerts are reserved for user-selected events such as a correction to a paper
used in a project, a watched release, or a deadline. Reading streaks and an
ever-growing unread badge are unnecessary for the intended research outcome.

### Familiarity and exploration controls

Offer explicit “focus on my active work,” “explore adjacent areas,” and
“teach foundations” controls. New researchers need older foundational work
alongside frontier material; new publication date does not imply first learning
priority. Familiarity is user-declared or suggested and editable, not inferred
as a mastery judgment from clicks.

## A concrete ML scenario

This is an illustrative workflow, not a claim about a particular new paper.

The user watches memory for agents, efficient sequence models and evaluation
methods, and has a project to build a small agent on limited hardware. A new
paper, its associated repository and three news stories arrive. The app groups
these into one development while preserving all sources.

The briefing explains that the proposed technique changes how memory is
selected; it does not claim the technique is universally better. “Why this
matters to you” links it to the user's retrieval-latency constraint. The source
profile shows which material is available and whether performance was measured
under comparable model sizes and budgets.

The user asks whether the idea applies to their current retrieval approach.
The research desk brings the two source dossiers together, explains the
relevant prerequisite, and records which claimed advantages depend on a
different task or resource envelope. An inferred transfer is labelled as a
hypothesis.

The user saves a small experiment: same task set, same model and budget,
baseline retrieval versus the proposed selection rule, with answer quality,
latency, memory size and failures measured separately. The app drafts the
brief and the user runs it elsewhere. On return, attached results update the
research question and influence what future alerts are useful. A later paper
revision triggers a change notice because the project depended on that source.

## Needs that should not be lost in implementation

| Need | Required product behavior |
|---|---|
| Broad fields with honest coverage | Searchable multilevel topic picker, aliases and free-form questions; show which sources can actually cover a selected field |
| Relevance tuning | Seeds, exclusions, reasons for dismissing, source weights and temporary mutes; an explanation of each recommendation |
| Mixed papers and news | Distinct source types and publication status; clustered stories; links to original research/releases |
| Changing evidence | Separate publication, first-seen, retrieval and revision dates; preserve versions and notify on meaningful saved-source changes |
| Negative evidence | Look for competing results and limitations; distinguish “searched and not found” from “there is no evidence” |
| Learning support | Prerequisite explanations, glossary and depth control; no false claims that reading equals mastery |
| Source gaps | Visible abstract-only, unavailable or stale states and a useful fallback |
| Research memory | Save/read/snooze state, notes, annotations, open questions, previous answers and experiment status survive refresh and restart |
| User control | Preview a watch's first results and exclusions before enabling it; pause, edit, export and delete |
| Bounded attention and spend | Finite briefing, quiet hours/cadence, on-demand depth and meaningful changes rather than a notification for every ingestion |
| Portability | Export selected sources, citations, notes, questions and experiment briefs in standard practical formats |
| Reading comfort | Responsive desk, keyboard access, source links with locations, readable equations, mobile triage and restored reading position |

## First complete slice and later expansion

The first slice should complete **choose interests and one question → preview
watch → collect from a bounded source set → inspect a finite briefing → open
one source-backed investigation → save a research note or experiment brief →
return to it tomorrow**. Give the user the breadth of topic navigation early,
while stating the narrower live-source coverage accurately.

Ship a functioning metadata-first version of that loop before funding
generation: open sources in the research desk, take linked notes, save reading
questions and export them. With an approved inference provider, the same desk
adds source-backed explanations and investigation actions, with a visible cap
and cancel behavior. Mock responses qualify UI states but must not appear as
live generated insights.

The initial research desk needs a source dossier, citations, persistent notes
and a few focused agent actions. It does not need a fully automatic knowledge
graph, autonomous experimentation, email/newsletter publication, a curriculum
platform, training a recommendation model or all enterprise identity work to
be useful to its owner.

After the first slice works in daily use, expand in this order as evidence
supports it: better source and revision coverage; paper comparisons and
relationship views; library interoperability; experiment/result tracking;
weekly synthesis and richer idea workflows. Add hosted delivery or additional
channels only after deciding where the app runs and which notifications are
useful. A sleeping laptop cannot provide a reliable always-on service.

For acceptance, have the owner perform the actual daily and deep-read tasks
with a predeclared sample, including irrelevant items, missing full text,
duplicate coverage and a changed source. Measure relevance judgments, source
inspection success, useful actions saved, correction rate, attention/time cost
and spend. Daily activity or a beautiful feed alone does not establish useful
research support. The current repository's primary metric and source-scope
defects from the [state review](../10-current-state-review-2026-11-02.md) must
not be relabelled as proof that generated explanations are trustworthy.
