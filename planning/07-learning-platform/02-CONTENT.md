# Learning platform — content and curriculum strategy (02)

> **Status: PROPOSED (2026-08-29).** Planning document only — no code,
> no schema migrations, no commitments. Sibling documents in this
> folder (00 — vision/scope, 01 — product/architecture, 03 —
> follow-on) are owned by other planning passes; this document is the
> content and curriculum strategy and defers platform-wide decisions
> to them. **Every legal/licensing note below is a good-faith reading
> of public terms as of 2026-08-29, with sources cited — all of it
> needs owner/counsel confirmation before anything ships.**

The platform's durable asset is not the UI and not the agent — it is
a **content graph**: topics, prerequisites, and curated resources that
a learning agent can plan over the same way the research agent plans
over papers today. This document designs that graph, the pipelines
that fill it, the quality gates that keep it honest, and the smallest
version that can ship.

Guiding constraints, inherited from how this repo already operates:

1. **Reuse the paper machinery.** `src/tools/` already searches,
   fetches, parses, chunks, embeds, caches, and dedupes papers.
   Content curation is the same shape of problem; every pipeline
   below names the module it reuses.
2. **Follow the storage matrix.** Every new stateful concern gets one
   setting and a pluggable backend, local-dev default first
   (`docs/architecture.md` § Storage matrix).
3. **Honesty is a product feature.** This repo names its errors
   honestly (ADR 0041) and refuses to fake states. Extended to
   pedagogy: we never present generated content as authored, curated
   content as ours, or a link as more than a link.

---

## 1. The content model

### 1.1 Entities

Five first-class entities. Everything else is an edge or an attribute.

**Topic** — the atomic unit of "something you can know."
Fine-grained: not "deep learning" but "backpropagation,"
"cross-entropy loss," "KV cache," "LoRA." Topics are the graph's
nodes; resources attach to them, prerequisites order them, learner
state is tracked against them. Target granularity: a topic is
learnable in one sitting (30–120 min of study).

**Resource** — one addressable piece of learning material. Subtypes
share a table with a `kind` discriminator:

| `kind` | What it is | Content lives |
|---|---|---|
| `video` | A curated YouTube video | On YouTube — we store the video ID + our metadata, render via embed |
| `paper` | An arXiv/S2 paper | Metadata + our briefing here; full text stays in the existing `paper_cache` (internal use only, § 3.2) |
| `lesson` | An original unit we authored (agent-drafted, human-approved) | Fully ours, in Postgres |
| `exercise` | A practice activity (coding task, derivation, quiz) | Fully ours; always labeled generated when generated |
| `external_course` | A link-out to a course we don't host (fast.ai, MIT OCW, …) | Elsewhere — we store the link, license note, and our framing text |

**Course** — an ordered container: `course → units → lessons/activities`.
A course is *editorial*, not structural: it is a named, versioned
selection of resources with connective prose. Structurally it is just
a `path` (below) with `kind = 'course'` and human-authored interstitials.

**LearningPath** — an ordered sequence of resources that takes a
learner from a stated starting point to a stated goal. Two flavors:
- **Flagship paths** — hand-finalized, versioned, marketed ("LLMs
  from scratch"). These are the product's front door.
- **Assembled paths** — generated per learner by the planning agent
  from the graph (§ 1.4), clearly labeled as assembled.

**LearnerTopicState** — per-learner, per-topic: `unseen / in_progress
/ self_reported_known / assessed`. This is what makes path assembly
personal. (Learner identity itself is a sibling-doc concern —
multi-tenancy scope MT-01 already exists in the frontend-revamp
record; this doc only claims the table.)

### 1.2 Schema sketch

Postgres, per the storage matrix. New concern rows the matrix would
gain (same pluggable pattern as `paper_cache`):

| Concern | Setting | Options (default first) | Shared across workers? |
|---|---|---|---|
| Content graph (topics, resources, paths) | `content_store` | `memory` / `postgres` | Postgres only |
| Learner state | (follows `content_store`) | `memory` / `postgres` | Postgres only |
| Curation queue + link-check schedule | (follows `job_store`) | `memory` / `redis` | Redis only |
| YouTube quota budget counter | `rate_limit_backend` (reused) | `memory` / `redis` | Redis only |

Sketch (illustrative DDL, not a migration):

```sql
CREATE TABLE topics (
    topic_id      TEXT PRIMARY KEY,          -- slug: 'backpropagation'
    name          TEXT NOT NULL,
    summary       TEXT NOT NULL,             -- 2-3 sentences, ours
    difficulty    SMALLINT NOT NULL,         -- 1 intro .. 5 research-edge
    est_minutes   INTEGER NOT NULL,          -- honest median, not marketing
    embedding_key TEXT,                      -- content hash into embedding_cache
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE topic_prereqs (
    topic_id   TEXT REFERENCES topics,
    prereq_id  TEXT REFERENCES topics,
    strength   TEXT NOT NULL DEFAULT 'required',  -- 'required' | 'helpful'
    PRIMARY KEY (topic_id, prereq_id)
    -- application-level acyclicity check on insert; the prereq
    -- relation must stay a DAG or path assembly is unsound
);

CREATE TABLE resources (
    resource_id    TEXT PRIMARY KEY,         -- namespaced: 'yt:<video_id>',
                                             -- 'arxiv:2311.09000', 'lesson:<slug>'
    kind           TEXT NOT NULL,            -- video|paper|lesson|exercise|external_course
    title          TEXT NOT NULL,
    canonical_url  TEXT NOT NULL,            -- the link-out / embed target
    source         TEXT NOT NULL,            -- 'youtube'|'arxiv'|'s2'|'original'|'ocw'|...
    license_note   TEXT NOT NULL,            -- human-readable posture, e.g.
                                             -- 'YouTube embed only; metadata refreshed <=30d'
    provenance     TEXT NOT NULL,            -- 'curated' | 'generated' | 'authored'
    difficulty     SMALLINT,
    est_minutes    INTEGER,
    body           TEXT,                     -- ONLY for kind in (lesson, exercise);
                                             -- NULL for video/paper/external_course
    metadata       JSONB NOT NULL DEFAULT '{}',  -- per-kind fields, see pipelines
    status         TEXT NOT NULL DEFAULT 'proposed',
                   -- proposed -> approved -> published -> stale -> retired
    reviewed_by    TEXT,                     -- human approver; NULL until approved
    last_verified  TIMESTAMPTZ,              -- link-check / metadata-refresh clock
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE resource_topics (
    resource_id  TEXT REFERENCES resources,
    topic_id     TEXT REFERENCES topics,
    role         TEXT NOT NULL DEFAULT 'teaches',  -- teaches|assumes|mentions
    rank_score   REAL,                        -- rubric score (0-1) for ordering
    PRIMARY KEY (resource_id, topic_id, role)
);

CREATE TABLE paths (
    path_id     TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,               -- 'flagship' | 'course' | 'assembled'
    title       TEXT NOT NULL,
    goal        TEXT NOT NULL,               -- what the learner can do at the end
    version     INTEGER NOT NULL DEFAULT 1,  -- flagship paths are versioned, never
                                             -- silently mutated under a learner
    learner_id  TEXT,                        -- NULL for flagship/course
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE path_items (
    path_id      TEXT REFERENCES paths,
    position     INTEGER NOT NULL,
    resource_id  TEXT REFERENCES resources,
    interstitial TEXT,                       -- connective prose ("why this next");
                                             -- provenance-labeled like any content
    PRIMARY KEY (path_id, position)
);

CREATE TABLE learner_topic_state (
    learner_id  TEXT NOT NULL,
    topic_id    TEXT REFERENCES topics,
    state       TEXT NOT NULL,               -- unseen|in_progress|self_reported_known|assessed
    evidence    JSONB,                       -- quiz results, completion events
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (learner_id, topic_id)
);
```

Design notes:

- **`resource_id` namespacing mirrors the existing dedup discipline.**
  `arxiv_search.canonical_paper_key` already collapses versioned/
  unversioned arXiv URLs to `arxiv:<id>`; paper resources use exactly
  that key, so a paper the research agent has already cached is the
  *same row identity* the learning graph references — no second
  identity scheme.
- **`body` is NULL for anything we don't own.** The schema physically
  cannot "accidentally" store a video transcript or a paper's full
  text in the content graph. Paper full text stays where it already
  lives — the internal `paper_cache` table (ADR 0028) — under the
  internal-analysis posture of § 3.2.
- **`provenance` is non-nullable and three-valued.** Every rendering
  surface must display it. `curated` = someone else made it, we chose
  it; `generated` = the agent wrote it, a human approved it;
  `authored` = a human wrote or substantially rewrote it. There is no
  fourth value and no NULL, so "unlabeled" is unrepresentable.
- **`status` is a queue, not a flag.** `proposed` rows are the
  agent's suggestions; nothing renders until `approved` (§ 4).
- **Topic embeddings reuse `embedding_cache`.** `topics.embedding_key`
  is the content hash of `name + summary` encoded through
  `embeddings.encode_texts`, so topic↔resource matching runs on the
  same MiniLM vectors, the same cache table, and the same
  crash-containment settings (ADR 0052) as paper ranking.

### 1.3 How a course is structured

```
Course ("LLMs from scratch")
└── Unit 1: Tokens and embeddings
    ├── Lesson  (authored/generated+approved prose, kind=lesson)
    ├── Video   (curated, embedded, kind=video)
    ├── Paper   (link-out + our briefing, kind=paper)
    └── Activity (exercise or quiz, kind=exercise)
└── Unit 2: Attention
    └── ...
```

A unit covers 1–3 topics. A lesson is the connective tissue — it
frames the topic, hands off to the curated video or paper, and closes
with the activity. This is deliberately the *inverse* of a MOOC: the
scarce thing we produce is framing and sequencing, not lecture
content. The lecture content already exists in the world and is
better than what a small team can author (§ 3.3 is honest about this).

### 1.4 Path assembly — how the agent plans over the graph

Assembly is classical planning over a DAG, not an LLM free-for-all:

1. **Goal → topic set.** The learner's stated goal is embedded
   (`encode_texts`) and matched to goal topics; the LLM proposes, the
   graph disposes — only topics that exist in the graph can be
   targeted.
2. **Prerequisite closure.** Walk `topic_prereqs` backwards from the
   goal topics; subtract topics whose `learner_topic_state` is
   `assessed` or `self_reported_known` (with `helpful`-strength
   prereqs droppable under time pressure).
3. **Topological order** with difficulty as tiebreaker. Cycle
   detection at write time (see DDL note) keeps this sound.
4. **Resource selection per topic.** For each topic in order, pick
   `approved`+`published` resources by `rank_score`, filtered by the
   learner's format preferences and time budget. Prefer one video OR
   one lesson plus one activity per topic; papers enter only when the
   path's goal is paper-literacy or the learner opts in.
5. **Label and persist** as an `assembled` path, rationale included
   as interstitials marked `generated`.

Determinism matters: steps 2–4 are pure graph operations that can be
unit-tested without any model call, the same testing posture the
supervisor loop earned (planning is cheap and checkable; only step 1
and interstitial prose spend tokens). Time and difficulty estimates
sum along the path so the learner sees an honest total before
starting.

---

## 2. Curation pipelines

### 2.1 YouTube

**Legal/practical position (verified 2026-08-29; needs owner/counsel
confirmation):**

- **Embedding is the compliant rendering path.** YouTube's ToS permit
  showing videos through the official embeddable player when the
  uploader has left embedding enabled, and the API Developer Policies
  prohibit modifying, blocking, or building on the player's
  functionality, running background/hidden players, and enabling
  autoplay-by-default. Downloading, caching, or storing copies of
  audiovisual content is prohibited without written approval.
  Sources: [YouTube ToS](https://www.youtube.com/static?template=terms),
  [Embed help](https://support.google.com/youtube/answer/171780),
  [Developer Policies](https://developers.google.com/youtube/terms/developer-policies).
- **Metadata storage is time-boxed.** Non-authorized (public) API
  data — titles, descriptions, channel names, caption-availability
  flags — may be stored for at most **30 days**, after which it must
  be refreshed or deleted. Some statistical metrics can be stored
  longer only under an approved derived-metrics use case.
  Sources: [Developer Policies](https://developers.google.com/youtube/terms/developer-policies),
  [derived-metrics policy](https://developers.google.com/youtube/terms/derived-metrics-policy).
- **No transcript scraping.** Both YouTube's ToS ("no automated
  access… scrapers") and the Developer Policies (API clients must not
  scrape) rule out the popular third-party transcript grabbers. The
  API's caption *download* endpoint is scoped to videos the
  authenticated account owns, so third-party transcripts are off the
  table entirely; the compliant signal is the *caption-availability
  flag* from `videos.list` (`contentDetails.caption`), not the
  caption text. (Endpoint-scope detail is from API docs familiarity —
  verify against current `captions` reference before relying on it.)
  Sources: [ToS](https://www.youtube.com/static?template=terms),
  [Developer Policies](https://developers.google.com/youtube/terms/developer-policies).
- **Attribution and commingling.** Pages showing YouTube data must
  make YouTube clearly the source, and independently computed scores
  shown next to API data must be clearly disclosed as not-YouTube's.
  Our `rank_score` therefore renders (if at all) as "our curation
  score," never as a YouTube metric.
  Source: [Developer Policies](https://developers.google.com/youtube/terms/developer-policies).
- **Quota is the binding practical constraint.** Default allocation
  is 10,000 units/day; `search.list` costs **100 units/call** while
  `videos.list` costs **1 unit**. A naive search-driven curator burns
  the whole day's quota in ~100 searches. Quota increases require a
  compliance audit.
  Sources: [Quota & compliance audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits),
  [practitioner write-ups](https://dev.to/qcrao/what-i-learned-squeezing-the-youtube-data-api-v3-quota-for-a-side-project-3304).

**What we store vs. don't:**

| Store (30-day refresh clock via `last_verified`) | Never store |
|---|---|
| `video_id` (the durable key in `resource_id = 'yt:<id>'`) | Video/audio files, thumbnails as files |
| Title, channel title, duration, caption-availability flag | Caption/transcript text |
| Publish date, embeddable flag, license field (`youtube`/`creativeCommons`) | View/like counts beyond 30d (no derived-metrics approval assumed) |
| Our own editorial fields: framing note, topic links, rubric score (ours, disclosed as ours) | Comments, user data of any kind |

The 30-day rule is operationalized on the existing pattern: a weekly
refresh job (same scheduling substrate as the job redriver) re-calls
`videos.list` in 50-id batches (1 unit each) and updates
`last_verified`; a row that can't be refreshed (deleted/private video)
transitions to `stale` and drops out of path assembly automatically.
For ~500 curated videos that is ~10 units/week of refresh — quota
noise.

**How the agent ranks and matches videos to topics:**

1. **Candidate discovery** is deliberately cheap on quota: curated
   *channel* seed list (3Blue1Brown, Karpathy, Yannic Kilcher,
   StatQuest, MIT OCW's channel, …) walked via playlist/upload
   listings (1 unit/page) instead of `search.list` (100 units), with
   `search.list` reserved for gap-filling on topics the seed channels
   don't cover. Budgeted through the existing rate-limiter substrate
   (Redis ZSET pattern, ADR 0037) so curation can never starve
   user-facing quota.
2. **Relevance**: title + description embedded via `encode_texts`,
   cosine-matched against topic embeddings; the LLM judges the top-k
   for actual pedagogical fit (a video *about* attention is not
   necessarily a video that *teaches* attention).
3. **Quality signals**, all compliant to hold under the 30-day clock
   or ours to keep: caption availability (accessibility + a weak
   quality proxy), channel presence on the vetted seed list (our
   editorial judgment, stored as ours), duration fit to the topic's
   `est_minutes`, recency for fast-moving topics.
4. Output is a `proposed` resource row — nothing publishes without
   the human gate (§ 4).

**Staleness:** embeddable/private/deleted state changes are caught by
the weekly refresh; content *obsolescence* (a 2023 "state of LLMs"
video) is handled by the freshness policy in § 4.3, which is
editorial, not mechanical.

### 2.2 Papers

**Legal/practical position (verified 2026-08-29; needs owner/counsel
confirmation):**

- **arXiv metadata (titles, authors, abstracts) is CC0** — usable
  freely; arXiv notes some abstracts may contain third-party content,
  so we render abstracts with attribution anyway.
  Sources: [arXiv licenses](https://info.arxiv.org/help/license/index.html),
  [reuse guidance](https://info.arxiv.org/help/license/reuse.html).
- **Full text is NOT redistributable by default.** Most arXiv papers
  carry only arXiv's non-exclusive distribution license; arXiv cannot
  grant us redistribution rights. Tools built on full text must link
  back to arXiv for downloads. A minority of papers are CC-BY/CC-0
  and could in principle be re-hosted, but per-paper license
  detection is fragile — so the uniform posture is simpler and safer.
  Sources: [reuse guidance](https://info.arxiv.org/help/license/reuse.html),
  [API ToU](https://info.arxiv.org/help/api/tou.html),
  [bulk data](https://info.arxiv.org/help/bulk_data.html).
- **Semantic Scholar** API data is licensed for access-and-display
  under AI2's terms (datasets under ODC-BY; some fields CC-BY-NC),
  with attribution/link-back expected and non-commercial restrictions
  on parts of the data. Free API keys carry modest rate limits. If
  the platform ever charges, the S2 usage terms need a dedicated
  counsel pass.
  Sources: [S2 license agreement](https://api.semanticscholar.org/license/),
  [S2 API](https://semanticscholar.org/product/api/license).

**The posture, in one table:**

| Content | What we do | Basis |
|---|---|---|
| Title/authors/abstract | Display, with link to arXiv abs page | CC0 metadata |
| Full text / PDF | **Never re-host or display.** Link out to arXiv. Full text enters only the internal `paper_cache` (already exists, ADR 0028) as input to briefing generation — same internal-analysis use the research agent performs today | arXiv default license; needs counsel confirmation that internal caching-for-analysis is fine to keep at platform scale |
| Short quotes inside briefings | Sparing, attributed, quote-marked | Ordinary quotation practice — not a verified legal safe harbor; counsel |
| Our briefings | Fully ours, labeled `generated`, human-approved | Original prose |
| S2 citation data | Used server-side for sequencing; any displayed S2-derived fact links back to S2 | ODC-BY attribution |

**Reading paths.** The flagship paper product: an ordered sequence of
papers where each entry is `[arXiv link] + [our briefing]`. The
briefing is the agent's genuine strength — it is literally what the
research agent already produces — recut for pedagogy:

- *Why this paper, why now in the sequence* (one paragraph),
- *What to read closely vs. skim* (keyed to sections the existing
  `chunker` already detects — Introduction, Method, Results…),
- *Vocabulary you need first* (links back into the topic graph),
- *What it got wrong / what superseded it* (temporal honesty; the
  contradiction-detection idea from `planning/02-feature-ideas.md`
  #4 and temporal awareness #3 land here as content features).

**Sequencing via Semantic Scholar.** `semantic_scholar.get_references`
already does one-hop citation traversal, and `search_papers` is
already built-but-unwired ("exposed for future portfolio work" — this
is that work). Citation-based sequencing heuristic: within a topic's
paper set, order by (a) citation-graph ancestry — a paper cited by
the others comes first; (b) year; (c) the agent's judged difficulty.
The reading path for "attention → transformers → scaling" writes
itself from the citation DAG plus editorial pruning.

**Ingestion reuse map** (this is the point of building on this repo):

| Existing module | Role in content curation |
|---|---|
| `arxiv_search.search_arxiv` | Candidate paper discovery per topic |
| `arxiv_search.canonical_paper_key` / `deduplicate_papers` | Resource identity — `arxiv:<id>` is the `resource_id` |
| `semantic_scholar.get_references` / `search_papers` | Citation-based sequencing + coverage beyond arXiv |
| `pdf_parser` + `paper_cache` | Full text into the internal cache for briefing generation (SSRF/size hardening from ADR 0033/0041 comes free) |
| `chunker` | Section detection feeding "read closely vs. skim" guidance |
| `embeddings.encode_texts` + `embedding_cache` | Topic↔paper matching on the shared MiniLM vectors |
| `http_session.build_retrying_session` | Link-rot checker (§ 4.2) and any new fetches |

### 2.3 Courses

"Free courses" means two different things and the platform must not
blur them:

**(a) Curated external courses** — link-outs with our framing.
License reality per anchor candidate (verified 2026-08-29; needs
owner/counsel confirmation):

| Source | License | What we may do | What we may NOT do |
|---|---|---|---|
| **fast.ai** (Practical Deep Learning, fastbook) | Notebook *code* GPLv3; *prose/markdown* explicitly "not licensed for any redistribution or change of format," no commercial/broadcast use ([fastbook README](https://github.com/fastai/fastbook)) | Link out; describe in our own words; sequence into paths | Mirror notebook prose, excerpt lessons into our lessons, re-host |
| **Karpathy — Neural Networks: Zero to Hero** | Repo (code) MIT ([LICENSE](https://github.com/karpathy/nn-zero-to-hero/blob/master/LICENSE)); videos are YouTube-hosted under YouTube's standard terms | Embed the videos via the compliant § 2.1 path; reuse/adapt repo code in exercises with attribution | Re-host or transcribe videos |
| **MIT OCW** | CC BY-NC-SA 4.0 for most materials ([OCW terms](https://ocw.mit.edu/pages/privacy-and-terms-of-use/)) | Excerpt and even adapt with attribution + license link — **but** derivatives must be shared under the same NC license | Use adapted OCW material anywhere a commercial tier could touch it; some OCW items are third-party "all rights reserved" — per-item check required |

The OCW ShareAlike/NonCommercial pair is the sleeper risk: if any
future monetization is on the table (sibling docs' call), OCW-derived
material either stays out or is confined to a provably free tier.
Default recommendation: **link-out + own framing for everything**,
adaptation rights treated as a bonus we mostly don't exercise.

**(b) Original units** — lessons and activities we produce,
agent-drafted under the § 5 rules, human-reviewed, labeled.

**Honest authoring-cost math.** A single good lesson (frame → teach →
activity, reviewed) is realistically **3–6 human-hours** even with
the agent drafting: review of technical claims, exercise validation,
and voice-editing dominate, not first-draft typing. A 10-unit course
at 2 lessons/unit is therefore ~60–120 hours of human time. Nobody
should pretend a solo maintainer produces three original courses; the
model that works at this team size is **thin original connective
tissue over strong curated spines** — which is also pedagogically
defensible, because Karpathy's attention video does not need a
replacement, it needs a prerequisite check-in front of it and an
exercise behind it.

**Cold-start flagship paths (three, not more):**

1. **ML fundamentals** — spine: StatQuest/3Blue1Brown video sequence
   + selected MIT OCW lectures (linked); our lessons carry
   definitions, notation, and exercises. Difficulty 1–2.
2. **LLMs from scratch** — spine: Karpathy Zero-to-Hero embeds +
   MIT-licensed repo code as exercise scaffolding; our lessons bridge
   into the modern stack (RLHF, inference, evals) where his series
   stops. Difficulty 2–4.
3. **Reading your first papers** — the differentiated one; no
   external spine exists. A 8–10 paper reading path (e.g. word2vec →
   seq2seq → attention → Transformer → BERT/GPT lineage → scaling
   laws → RLHF → a current paper slot that rotates) with full
   briefing companions. This is the path only *this* repo can build,
   because the briefing machinery already exists. Difficulty 3–4.

fast.ai is referenced from paths 1–2 as a recommended parallel track
(link-out only, per its license).

---

## 3. Quality control

### 3.1 The vetting pipeline

Every resource moves `proposed → approved → published`, and only a
human moves anything past `proposed`:

1. **Agent proposes** — discovery pipelines (§ 2) write `proposed`
   rows with a machine-readable justification in `metadata`
   (relevance score, quality signals, topic links).
2. **Agent judges by rubric** — a second, separate pass (same
   separation-of-roles logic as the existing critic/verifier agents)
   scores the proposal 0–1 per dimension and writes `rank_score`:
   - *Correctness risk*: does it teach anything now known wrong?
   - *Pedagogical fit*: teaches the topic vs. merely mentions it
   - *Prerequisite honesty*: assumes what its topic edges say
   - *Production quality*: audio/legibility/structure
   - *Longevity*: fundamentals (slow decay) vs. news (fast decay)
3. **Human approves** — a review queue (UI is a sibling-doc concern)
   showing proposal + rubric verdict + the embed/link preview. Human
   approves, edits topic links, or rejects-with-reason; rejects are
   kept (this folder's own rule: record rejected ideas and why),
   giving the judge pass a growing calibration set.

The eval harness pattern transfers: rubric-judged curation decisions
against a small human-labeled golden set becomes a curation-quality
metric alongside the existing four report metrics.

### 3.2 Attribution rules

- Every `curated` resource renders creator name + source, always
  linked to the canonical origin. YouTube surfaces carry YouTube
  branding per Developer Policies; S2-derived facts link back to
  Semantic Scholar; OCW-derived anything carries the CC BY-NC-SA
  notice + link.
- Every `generated` item is labeled at the point of display ("Written
  by the learning agent, reviewed by <name>") — not in a footer, not
  in an about page.
- Our scores are presented as ours (Developer Policies commingling
  rule generalized to every source).

### 3.3 Link rot and freshness

**Link rot (mechanical).** Weekly job over all `published` resources:
YouTube rows refresh via batched `videos.list` (also satisfying the
30-day metadata clock); non-YouTube rows get a HEAD/GET through
`build_retrying_session`. Failures mark `stale` — which *immediately*
removes the row from path assembly and flags any flagship path that
contained it for editorial repair. Dead links in a learning path are
a product-killing experience; this must be boring and automatic.

**Freshness (editorial), tiered by decay rate:**

| Tier | Examples | Review cadence |
|---|---|---|
| Fundamentals | backprop, attention math | 12 months |
| Stable-practice | fine-tuning methods, eval practice | 6 months |
| Fast-moving | model landscape, SOTA claims, tooling | 6–8 weeks; prefer a rotating "current" slot over dated claims |

Rule for a monthly-moving field: **dated framing beats updated
content.** A briefing that says "as of mid-2026" and shows its date
ages honestly; silently-edited content that pretends to be current
does not. Every lesson/briefing displays its `updated_at`.

---

## 4. Agent-generated content — where it is and isn't safe

The repo's honesty rules (honest error names over comfortable
conflations — ADR 0041; no fake states) extend to pedagogy directly.

**Safe and valuable (always labeled `generated`, always
human-approved before `published`):**

- **Briefing companions** to papers — the existing core competence.
- **Exercises and quizzes** — high value per human-review-minute;
  review is verification (does the exercise work, is the answer key
  right), which is much cheaper than authoring.
- **Glossary entries** — short, checkable, link into the topic graph.
- **Path interstitials and rationales** — "why this next" prose.
- **Prerequisite-edge proposals** — the agent suggests graph edges;
  the graph is small enough for human sign-off on every edge, and a
  wrong prerequisite edge silently corrupts every path through it.

**Not safe:**

- **Generating whole "courses" and implying authorship.** A wall of
  generated lessons presented as a taught course is the pedagogical
  equivalent of a fake green checkmark. Generated lessons are fine;
  they say so, and a human reviewed them.
- **Unreviewed factual claims in anything published.** `proposed` is
  the only state agent output can reach on its own. No exceptions,
  including "small" regenerations of existing approved content — a
  regeneration re-enters the queue.
- **Summarizing videos we can't legally read.** No transcript
  scraping means no "AI summary of this video" feature built on
  scraped captions. The briefing model applies to papers because we
  can lawfully process paper text internally; it does not transfer to
  YouTube content. Our video framing notes are written from the
  curator's judgment of the video, not from its transcript.
- **Assessment theater.** Quizzes measure recall of what the path
  taught; the platform must not imply certification or mastery
  guarantees. "Assessed" in learner state means "passed our quiz,"
  and the UI says exactly that.

---

## 5. Cold-start plan

**Ships at MVP (numbers are the plan, not aspirations):**

| Asset | Count | Produced by |
|---|---|---|
| Topics | ~40 (fundamentals 15, LLM stack 15, paper-reading craft 10) | Agent-proposed taxonomy, human-finalized in review sessions |
| Prerequisite edges | ~70 | Agent-proposed, 100% human-approved |
| Flagship paths | 3 (§ 2.3) | Human-assembled from the graph, agent-drafted interstitials |
| Curated videos | ~45 (≈15/path) | § 2.1 pipeline from ~8 seed channels |
| Curated papers | ~15 (10 in the reading path + 5 across the others) | § 2.2 pipeline |
| Paper briefings | 15 | Agent-generated, human-reviewed (the long pole: ~1–2 review-hours each) |
| Original lessons | ~12 (thin connective tissue only) | Agent-drafted, human-rewritten (~4 h each) |
| Exercises/quizzes | ~30 | Agent-generated, human-verified (~30 min each) |
| External course link-outs | 3–5 (fast.ai, OCW picks) | Human-selected |

Rough human cost to MVP: **~120–160 hours** (briefings ~25, lessons
~50, exercises ~15, curation review ~15, taxonomy/edges ~10, slack
~20). That is a real number; sibling docs should budget against it
rather than assume content is free because an agent is involved.

**Weekly maintenance load thereafter:**

- Automatic: link-check + YouTube metadata refresh (~10–50 API
  units/week — nowhere near quota), staleness transitions, curation
  pipeline batches writing `proposed` rows.
- Human: **~2–4 hours/week** — approve/reject the proposal queue
  (~10–20 items), repair any path a `stale` transition broke, touch
  the fast-moving-tier items on rotation, refresh the rotating
  "current paper" slot monthly.
- Quota posture: default 10,000 units/day is comfortably sufficient
  for curation at this scale *if* discovery stays channel-walk-first
  (§ 2.1); a `search.list`-heavy design would need the compliance
  audit almost immediately.

**What explicitly does not ship at MVP:** learner-assembled paths
beyond the three flagships can ship in "preview" labeled as
assembled; assessments beyond simple quizzes; any OCW-adapted
(vs. linked) material; any transcript-dependent feature; more than
three paths.

---

## 6. Open content questions for the owner

1. **Original-content investment.** The § 5 plan spends ~120–160
   human-hours on thin-connective-tissue content. Is that budget
   real? If it's half that, the honest cut is 2 paths (drop "ML
   fundamentals," where external alternatives are strongest), not
   thinner review.
2. **Licensing risk appetite / commercial posture.** Several
   postures depend on whether the platform is forever-free:
   MIT OCW's NC clause, Semantic Scholar's non-commercial
   restrictions, and YouTube API audit posture all tighten if money
   appears. Decision needed *before* content is built on OCW or
   S2-displayed data, and all § 2 legal notes need counsel
   confirmation regardless.
3. **Internal full-text caching at platform scale.** The research
   agent caches parsed paper text for analysis today (ADR 0028).
   Does the owner want counsel sign-off that the same internal-only
   posture holds when briefing generation runs across a growing
   catalog, or should briefings regenerate from abstracts only for
   non-permissively-licensed papers?
4. **YouTube API compliance audit.** Do we design for the default
   quota indefinitely (the § 2.1 architecture can), or file for the
   audit early to unlock headroom — accepting that the audit also
   invites scrutiny of the storage model?
5. **Moderation and review authority.** Who besides the owner can
   approve `proposed → approved`? One reviewer is a bottleneck at
   ~10–20 items/week but keeps voice consistent; the alternative is
   a second reviewer + a written rubric with the owner auditing
   samples.
6. **Learner-visible generated content bar.** Is "generated, human-
   reviewed" labeling sufficient for lessons in flagship paths, or
   should flagship lessons require the stronger `authored`
   (human-rewritten) bar, reserving `generated` for briefings,
   exercises, and glossary entries?
7. **Rotating "current" slots.** The freshness design (§ 3.3) leans
   on monthly-rotated slots for fast-moving topics. Is a monthly
   editorial commitment acceptable, or should fast-moving topics be
   excluded from flagship paths entirely at MVP?

---

## Sources

Licensing/ToS claims verified 2026-08-29 (all need owner/counsel
confirmation):

- YouTube: [Terms of Service](https://www.youtube.com/static?template=terms) ·
  [API Developer Policies](https://developers.google.com/youtube/terms/developer-policies) ·
  [API Services ToS](https://developers.google.com/youtube/terms/api-services-terms-of-service) ·
  [Derived-metrics/data-storage policy](https://developers.google.com/youtube/terms/derived-metrics-policy) ·
  [Quota and compliance audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits) ·
  [Embed videos help](https://support.google.com/youtube/answer/171780) ·
  quota practitioner reports: [dev.to (qcrao)](https://dev.to/qcrao/what-i-learned-squeezing-the-youtube-data-api-v3-quota-for-a-side-project-3304),
  [getphyllo.com](https://www.getphyllo.com/post/youtube-api-limits-how-to-calculate-api-usage-cost-and-fix-exceeded-api-quota)
- arXiv: [Licenses](https://info.arxiv.org/help/license/index.html) ·
  [Permissions and reuse](https://info.arxiv.org/help/license/reuse.html) ·
  [API Terms of Use](https://info.arxiv.org/help/api/tou.html) ·
  [Bulk data access](https://info.arxiv.org/help/bulk_data.html)
- Semantic Scholar: [Dataset license agreement](https://api.semanticscholar.org/license/) ·
  [API license page](https://semanticscholar.org/product/api/license)
- MIT OCW: [Privacy and Terms of Use](https://ocw.mit.edu/pages/privacy-and-terms-of-use/) ·
  [Citation guidance](https://mitocw.zendesk.com/hc/en-us/articles/4414774353051-What-are-the-requirements-of-use-for-MIT-OpenCourseWare)
- fast.ai: [fastbook README (license section)](https://github.com/fastai/fastbook)
- Karpathy: [nn-zero-to-hero MIT LICENSE](https://github.com/karpathy/nn-zero-to-hero/blob/master/LICENSE)
