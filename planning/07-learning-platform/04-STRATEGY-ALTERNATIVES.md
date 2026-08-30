# Learning platform — strategy critique and alternatives (04)

> ## ⚠ STATUS: PROPOSED
>
> **Nothing in this document is approved, decided, or implemented.**
> This is the strategy-critique document for the proposed learning
> platform: the one chartered to ask whether the chosen idea is the
> right idea at all, what the alternatives are, and what the whole bet
> stands on. It follows the repo's proposal discipline
> ([`docs/proposals/README.md`](../../docs/proposals/README.md)) —
> including its rule that *"the recommendation section is worthless if
> the rejected options are strawmen."* Here that cuts the other way
> too: this document fails if it rubber-stamps the platform, and it
> fails equally if it strawmans the sibling plans, which are strong
> work and are engaged on their actual numbers throughout.

- **Workstream**: LP-04
- **Date**: 2026-08-29
- **Decider**: kudratsingh — **pending**
- **Siblings**: [`00-VISION.md`](00-VISION.md) (vision, personas,
  competitive scan), [`01-LEARNING-AGENT.md`](01-LEARNING-AGENT.md)
  (agent design and per-learner economics),
  [`02-CONTENT.md`](02-CONTENT.md) (content graph, curation,
  licensing), [`03-ARCHITECTURE-ROADMAP.md`](03-ARCHITECTURE-ROADMAP.md)
  (delta architecture, ~71-work-order phased roadmap). All four plan
  the *chosen* idea. None was chartered to question the choice. This
  one is.
- **Also grounded in**: the repo's own history as a portfolio
  artifact ([`planning/06-portfolio-polish.md`](../06-portfolio-polish.md),
  [`planning/README.md`](../README.md)), the roads not taken
  ([`planning/01-enterprise-gaps.md`](../01-enterprise-gaps.md),
  [`planning/02-feature-ideas.md`](../02-feature-ideas.md),
  [`planning/05-agentic-upgrade-plan.md`](../05-agentic-upgrade-plan.md)),
  and the shipped system ([`README.md`](../../README.md),
  [`docs/architecture.md`](../../docs/architecture.md),
  [`docs/revamp/STATUS.md`](../../docs/revamp/STATUS.md)).

Judgment calls are marked **[judgment]**. External sources were
checked 2026-08-29 and are cited inline plus indexed in §7.

---

## 0. The one-paragraph verdict, up front

The sibling documents are the best planning work in this repository:
grounded, costed, honest about their own weakest links. And precisely
*because* they are honest, they jointly document a bet whose binding
constraint (engagement) is acknowledged but not cheaply tested, whose
distribution story does not exist in any of the four documents, whose
economics rest on numbers the repo's own eval discipline says to
treat as hypotheses, and whose ~71-work-order roadmap places the
first real engagement data *after* identity, content, scheduler, and
email infrastructure are built. Meanwhile the repo's entire history —
including the owner's revealed spending decisions — is that of a
portfolio artifact, not a service. The recommendation (§6) is not
"kill it": it is to name the objective function first, then buy the
platform's key information for roughly 2–10% of its build cost via a
wedge feature the vision document itself ranks as differentiator #1,
before any of L0's fourteen work orders start.

---

## 1. What is the owner actually optimizing for?

This section gates everything else. The four sibling documents assume
the answer; the repo's record suggests it is genuinely open. Four
plausible objective functions, and why the right next move differs
under each:

### O1 — Portfolio / career artifact

The repo's documented, explicit historical objective.
[`planning/06-portfolio-polish.md`](../06-portfolio-polish.md) is
titled *"what turns the repo into a resume artifact"* and defines
success as *"the reviewer's 90-second experience."*
[`planning/05-agentic-upgrade-plan.md`](../05-agentic-upgrade-plan.md)
§3 contains a literal **"Interview framing (verbatim)"** block.
[`planning/README.md`](../README.md) calls 06 *"the presentation
layer that makes the repo a resume artifact."* Under O1, success is a
reviewer's belief in the owner's engineering judgment, and the
scarcest resource is *legibility*, not users.

**Right next move under O1**: finish the artifact (fund the eval
numbers, close the reserved items in
[`docs/revamp/STATUS.md`](../../docs/revamp/STATUS.md)), and add at
most one legible, demoable capability. A 71-work-order consumer
platform with recurring bills is likely *negative* ROI under O1: it
converts a completed, comprehensible "agentic research system" story
into a sprawling, half-launched edtech story (§3, column
"portfolio proof").

### O2 — A real product with real users

The platform documents implicitly assume this. Under O2, success is
retained humans, and the scarcest resources are **distribution** and
**the owner's sustained operational attention** — neither of which any
sibling document budgets (§4, A6/A5). Under O2 the correct next move
is the cheapest possible demand-and-engagement test, *not* the
platform build: the entire venture-methodology point of a wedge is
that code is the most expensive way to learn whether anyone comes.

### O3 — Revenue

Nobody has stated this goal, but 01's economics
([`01-LEARNING-AGENT.md`](01-LEARNING-AGENT.md) §6.4 mentions "a
plausible $10–15 subscription") smuggle it in. Under O3 the analysis
changes hardest: consumer learning subscriptions are a brutal
category (churn, support, payments, tax), and the honest comparison
set is not "can we build it" but "would this beat the same hours
spent on salary-maximizing career work" — which for a strong IC it
almost never does. **[judgment]** Under O3 the researcher-tools
market (§2.C) at least has demonstrated willingness-to-pay; the
free-courses-plus-mentor shape has demonstrated cost.

### O4 — Learning-by-building

Also legitimate and historically real here: the supervisor loop,
eval harness, and revamp were partly built to *learn how to build
them*. Under O4 the platform is genuinely attractive — identity,
scheduling, email, content pipelines, and long-horizon agent memory
are all new problem shapes — and finishing/launching matters much
less than the build itself. But under O4 the recurring-cost and
maintenance commitments should be explicitly *not* made, because the
builder will leave when the learning is done, and a platform with
learners is the one artifact you cannot ethically abandon.

### 1.1 The revealed-preference datum that must be named

Every cost-bearing decision this repo has ever put to the owner is
still pending: the Hetzner deployment (≈€8–15/mo) is "blocked...
reserved for the user" ([`STATUS.md`](../../docs/revamp/STATUS.md));
**all 54 nightly eval runs from 2026-07-07 to 2026-08-29 failed on a
missing API-key secret** because a one-time campaign on the order of
$25 was never funded ([`README.md`](../../README.md) §Eval,
[`docs/eval.md`](../../docs/eval.md)); MT-01 sits PROPOSED. This is
not a criticism — reserving spend decisions is the repo's discipline
working as designed. But it is *evidence about the objective
function*: the platform plan requires an IdP, an email provider, a
server resize, funded content-generation campaigns, and open-ended
per-learner inference ([`03-ARCHITECTURE-ROADMAP.md`](03-ARCHITECTURE-ROADMAP.md)
§6.6 calls it "the first workstream whose approval creates recurring
bills"). If a ~$25 eval campaign has not cleared the bar in eight
weeks, either the objective function is O1/O4 (in which case the
platform is the wrong plan), or it is about to change (in which case
the owner should say so out loud, because every sibling document's
gates depend on it).

### 1.2 What this section asks of the owner

Pick one primary objective and at most one secondary. Do not proceed
to any alternative in §2 — including the platform — before answering.
§6.2 ranks the alternatives under each answer.

---

## 2. The alternatives, steelmanned

Six alternatives, each given its strongest honest case, its effort
shape, its reuse of existing machinery, and the risks that would kill
it. Effort sizes use the repo's work-order convention
([`docs/revamp/06-WORK-ORDERS.md`](../../docs/revamp/06-WORK-ORDERS.md)
§0; the revamp was 33 WOs).

### 2.A — The full learning platform, as planned

**Strongest case.** The sibling documents' argument is real: this
system has, shipped and tested, the four rarest ingredients of an
honest AI learning product — a pipeline that reads the live
literature, an HITL plan-review interaction that makes a plan *the
learner's*, an evidence/verifier stance that refuses to fake mastery,
and per-dollar cost machinery ([`00-VISION.md`](00-VISION.md) §1.1).
The reuse claims in [`01-LEARNING-AGENT.md`](01-LEARNING-AGENT.md)
§5.1 are cited module-by-module and mostly check out; the content
strategy's "thin original connective tissue over strong curated
spines" ([`02-CONTENT.md`](02-CONTENT.md) §2.3) is the only content
model a solo operator can run; and the roadmap's gates are genuinely
kill-capable ([`03-ARCHITECTURE-ROADMAP.md`](03-ARCHITECTURE-ROADMAP.md)
§6). If the Khanmigo engagement problem is solvable at all by anyone,
"the mentor is the front door, not a widget" is the right design
answer to it. And the payoff, if it works, is the only alternative on
this list that could become a durable product with compounding
value — the relationship *is* the moat.

**Effort shape.** ~71 WOs ±20% across 5 phases and 11 gates, 2.5–3×
the frontend revamp, with MT-01's six irreducibly-sequential gates at
the head (03 §6.6); 6–9 engineering weeks for the agent core alone
before UI (01 §5.2); ~120–160 human-hours of cold-start content plus
2–4 h/week forever (02 §5); the repo's first recurring bills.

**Reuses.** Nearly everything — that is its honest appeal (01 §5.1's
table; 03 §2).

**Kill risks.**
1. *Engagement* — the Khanmigo RCT's finding that only ~15% of
   students with a capable AI tutor used it ([00 §3.5](00-VISION.md));
   00 §6.3 adopts this as the kill-signal, but the roadmap measures
   it at Gate LG-2, ~43 WOs in (§4, A1).
2. *Commoditization by the frontier labs* — see §2.B; the sibling
   scan omits this entirely.
3. *Distribution* — no document says how learner #1 arrives (§4, A6).
4. *Solo-operator ops* — content review + user support + email
   deliverability + incident response is a permanent part-time job
   (§4, A5).
5. *Economics unmeasured* — 01's own words: "treat unmeasured numbers
   as hypotheses" (§4, A4).

### 2.B — The narrow wedge: ship "guided paper reading" inside the existing product

**Strongest case.** [`00-VISION.md`](00-VISION.md) §4.2 ranks its own
differentiators, and #1 is *"a mentor that reads with you — guided
reads of real papers, compiled for your goal at your level, citing
everything. No incumbent offers this."* That claim has only gotten
stronger since the scan was written, because everything *else* in the
mentor's differentiator stack is being commoditized at price zero:
OpenAI shipped ChatGPT Study Mode in July 2025
([Inside Higher Ed](https://www.insidehighered.com/news/tech-innovation/artificial-intelligence/2025/08/07/understanding-value-learning-fuels-chatgpts)),
Anthropic ships a Learning Mode with cross-conversation memory
([Northeastern's student guide](https://learning.northeastern.edu/ai-student-guides-using-claude-learning-mode-to-study)),
and Gemini ships Guided Learning — the 2026 framing in the trade
press is that the labs now "compete on pedagogy" and "the teaching
version is increasingly free"
([buildmvpfast education-AI survey](https://www.buildmvpfast.com/articles/best-llms-2026-guide/education-ai)).
A free general assistant with memory can already do "Socratic tutor,
adapts to my level, remembers me." What it structurally does *not* do
is what this repo's machinery does: parse an arXiv PDF into ranked
evidence chunks, ground every claim in `source_text`, verify
faithfulness at runtime, and present a paper as a guided,
checkpointed read. The wedge ships exactly that — the guided-read
session type (00 §5.3) and 02's flagship path #3, *"Reading your
first papers,"* which 02 itself calls "the differentiated one... the
path only *this* repo can build" — inside the existing Evidence
Workbench, behind a flag, with no identity system, no scheduler, no
email, and no content treadmill. If people come and return, the
platform thesis earns its next tranche; if they don't, ~90% of the
platform budget was never spent.

**Effort shape.** ~6–10 WOs **[judgment]**: a guided-read renderer on
the existing `ReportReader` surface (the reader "is, with small
changes, a lesson reader" — 03 §2.5); briefing-companion generation
for ~8–10 papers reusing the synthesis pipeline (02 §2.2's reading
path, at 02's own estimate of ~1–2 review-hours per briefing ≈ 15–25
human-hours total); a static path page; optionally 01's
`enable_learner_profile` in its explicitly-sanctioned single-human
mode (01 §1.3: "usable... for single-user deployments and dev —
honestly labeled as such"). A hand-run pilot of ≤5 invited users is
possible *without* MT-01 by issuing per-principal API keys — the
scoping half of multi-tenancy already exists (03 §2.3) — accepting
the shared-workspace caveats for a two-week test.

**Reuses.** The pipeline (planner→search→reader→synthesizer→critic),
the chunker's section detection, the evidence store, the report
surface, export, per-principal scoping, cost caps. This is the
highest reuse-to-new-code ratio of any alternative.

**Kill risks.** (1) A wedge inside a product with no users tests
engagement only if the owner *distributes* it — a Show HN /
r/MachineLearning / X post is part of the work order list, not an
afterthought. (2) Guided reads without spaced retrieval or a path may
under-represent the full mentor experience, biasing the test
pessimistic — acceptable, because a pessimistic-biased test that
*passes* is strong evidence, and 00 §4.2 predicts this feature is the
shareable one. (3) If it succeeds, there is a temptation to declare
the platform validated and skip the remaining rungs (§5); the ladder
exists to prevent exactly that.

### 2.C — Double down on the research tool (the researcher/grad-student wedge)

**Strongest case.** Dr. Chen (00 §2.3) is *already the natural user
of the product that exists*. The shortest path to real users may be
to serve her deeper rather than to build a second product for
personas the repo has never met: standing subfield queries, weekly
synthesized digests (the pipeline's native output), alerts, saved
workspaces (ideas 15/21/27/28 in
[`02-feature-ideas.md`](../02-feature-ideas.md) — the same ancestors
00 cites), team spaces later. The Papers with Code shutdown (00 §3.6)
left a real gap in task-level tracking, and "keeping up" is a felt,
recurring pain with demonstrated willingness-to-pay in the adjacent
market (Elicit and peers charge for exactly this class of work). The
evidence/verifier stance is the correct brand for expert users, and
every hour spent here compounds the portfolio story ("agentic
research system") instead of diluting it.

**Effort shape.** ~15–25 WOs **[judgment]**: saved/standing queries
(M), digest generation as a job kind (M–L), the deferred
`list_by_principal` jobs list (M — 03 §2.8 needs it anyway),
workspaces/tags (M), and — the honest drag — *alerts require the same
scheduler + email infrastructure as the learning platform's daily
loop* (03 §4.5), so the delivery-channel work is shared, not saved.
An in-app-only digest version defers that.

**Reuses.** Everything; the digest is literally the current product's
output on a schedule.

**Kill risks.** (1) *This market is crowded and consolidating*:
Elicit (138M+ papers), Consensus, SciSpace, Undermind, scite, STORM
occupy the search/extraction/synthesis niches
([2026 category surveys](https://listenlabs.ai/articles/top-ai-research-assistant-2026/),
[alternatives roundups](https://www.atlasworkspace.ai/blog/elicit-alternatives));
free personalized-alert tools like
[Scholar Inbox](https://www.scholar-inbox.com/)
([paper](https://arxiv.org/html/2504.08385v1)) and Semantic Scholar
feeds occupy the recommendation niche; and the frontier labs' Deep
Research modes bracket the whole category from above. A solo
operator's differentiation here is a thesis about *trustworthiness*
(the verifier stance) against funded teams — defensible as craft,
hard as distribution. (2) Elicit's own failure mode, named by 00
§3.7: a tool consulted at task time "owns a task, not a trajectory" —
weaker retention economics than a mentor, permanently. (3) The
academic market is small and price-sensitive.

### 2.D — The API / agent-platform play

**Strongest case.** The repo's most defensible artifact is not the UI
— it is the hardened pipeline surface: async jobs, SSE, HITL
interrupts, per-principal scoping, rate limits, cost caps, leases and
redrive, OpenAPI contract with drift checks. That is precisely the
part most builders of literature-aware products do not want to build.
Selling (or openly offering) "grounded literature synthesis as an
API" — submit a question, get back a cited, verified briefing with
its evidence chunks — turns every other company's learning platform,
research assistant, and internal tool into a distribution channel.
The enterprise ideas the repo already cataloged (private corpus #29,
budget controls #31, compliance mode #32 in
[`02-feature-ideas.md`](../02-feature-ideas.md)) all live naturally
here, and B2B/API products fit a solo operator's support model far
better than consumers do.

**Effort shape.** ~8–15 WOs **[judgment]**: self-serve key issuance
on top of the existing keystore, quota tiers (rate-limit machinery
exists), usage metering and billing (the genuinely new, genuinely
annoying part), webhooks (an acknowledged gap —
[`01-enterprise-gaps.md`](../01-enterprise-gaps.md) §6), API docs and
a landing page. Plus the same unbuilt distribution muscle as every
other alternative.

**Reuses.** The API surface nearly verbatim; the cost accumulator
becomes the metering meter.

**Kill risks.** (1) The capability is being commoditized fastest of
all: every frontier lab sells deep-research-shaped output through
their own APIs, and orchestration frameworks reproduce the pipeline
shape in an afternoon (the *hardening* doesn't reproduce in an
afternoon — but buyers can't see hardening on a landing page).
(2) An API product carries an implicit SLA; a solo operator on one
Hetzner box cannot honestly offer one. (3) Reselling inference means
fronting other people's LLM spend — the F4 global-cap problem
([`multi-tenancy.md`](../../docs/proposals/multi-tenancy.md)) at its
sharpest. (4) Finding B2B buyers is slower and colder than finding
learners.

### 2.E — Open-source flagship + content: the repo itself is the product

**Strongest case.** Under O1 — and partly under O2, where "users" are
*readers and engineers* — the most valuable asset here is not the
running service but the **build record**: 54+ ADRs, a gated
design campaign with independent reviews, an honest eval story that
refuses to fake numbers, threat models, cost engineering, and a
planning discipline most companies don't have. Almost nobody
publishes this. A deliberate campaign — a README-level "how this was
built" narrative arc, 3–6 deep-dive essays (the supervisor A/B story,
the HITL cost-control story, the "eval that was never funded" story —
which is *itself* a compelling essay about engineering honesty), and
the funded eval numbers as the capstone — turns the repo into a
teaching artifact with organic distribution (HN, newsletters, hiring
managers) at near-zero build cost and zero recurring cost. This is
also the only alternative whose success mode *increases* every other
alternative's chances, because it builds the audience that every
other alternative lacks (§4, A6).

**Effort shape.** ~0–3 WOs of code; ~20–60 hours of writing
**[judgment]**; one funded eval campaign (order-$25–75) so the
flagship claim ("measured, not vibes") is real.

**Reuses.** Everything, as subject matter. `docs/demo.md`, the
revamp evidence packs, and the ADR index are half the raw material
already.

**Kill risks.** (1) Writing at this quality is slow and the owner may
not enjoy it; an unwritten content plan is worth nothing. (2) Stars
and readers are not users; under a strict O2/O3 reading this
alternative punts. (3) The window matters: "how I built an agentic
system" essays are commodifying too — the differentiated angle is the
*discipline* (gates, evals, honesty), which is more evergreen but
niches the audience.

### 2.F — Declare completion: the project is finished

**Strongest case.** Every stated goal of this repository has been
met or exceeded. The 90-second reviewer experience
([`06-portfolio-polish.md`](../06-portfolio-polish.md)) exists;
Sprints 1–5, the hardening chain, and a 33-work-order design campaign
are on `main` with 1,447 Python tests and 2,970 web tests green on
every PR ([`README.md`](../../README.md)). The honest gap list is
short and cheap: fund one eval campaign so the numbers table stops
being empty, run the RR-02 screen-reader pass, decide the license,
optionally deploy once for a live demo URL — the exact "reserved for
the user" list in [`STATUS.md`](../../docs/revamp/STATUS.md) *is* the
completion checklist. Stopping at a finished, measured, deployed
artifact is a strictly better portfolio outcome than a half-built
platform, and it keeps every future option open at zero carrying
cost. Sunk-cost logic runs the other way here: the fact that the
machinery *could* power a learning platform is not a reason it
*should*.

**Effort shape.** ~1–3 WOs + one funded eval + the human passes.
Days, not months.

**Kill risks.** Only opportunity cost: if the owner's true objective
is O2/O3/O4, stopping forfeits it — but stopping *after* Rung 0–1 of
§5 forfeits almost nothing, because those rungs are also completion
work.

### 2.G — Noted and folded in

Two shapes considered and not given full sections: **enterprise/team
research spaces** (ideas 25/29/30) is a variant of C with longer
sales cycles — everything in C's kill list applies harder;
**"stop here" with no completion work** is F minus its cheap capstone
and is dominated by F.

---

## 3. The tradeoff matrix

Estimates, not measurements; sibling-doc numbers cited where they
exist, the rest **[judgment]**. "WO" per
[`06-WORK-ORDERS.md`](../../docs/revamp/06-WORK-ORDERS.md) §0 sizing;
the 33-WO revamp is the calibration anchor.

| | **A. Full platform** | **B. Guided-read wedge** | **C. Research double-down** | **D. API play** | **E. OSS flagship + content** | **F. Complete & stop** |
|---|---|---|---|---|---|---|
| **Build effort** | ~71 WOs ±20%, 11 gates, 2.5–3× revamp (03 §6.6); +120–160 h content (02 §5); 6–9 eng-wks agent core (01 §5.2) | ~6–10 WOs + ~15–25 h briefing review (02's per-briefing estimate) | ~15–25 WOs (scheduler+email shared with A if alerts ship) | ~8–15 WOs (billing/metering is the new hard part) | ~0–3 WOs + 20–60 h writing | ~1–3 WOs + human passes |
| **Ongoing cost / maintenance** | First recurring bills in repo history: IdP + email + resize ≈ €10–30/mo before LLM spend (03 §6.6); $3–7/mo per daily-active learner, $0.50–1.20 free tier (01 §6.4–6.5); 2–4 h/wk editorial forever (02 §5); ops on email deliverability + support | Near zero: no identity, no scheduler, no email; inference only when used (~$0.09/briefing-scale runs, README demo; ≤$0.75 learning-mode cap, 01 §6.3); briefing refresh optional | Moderate: alert infra ≈ platform's L2 email stack; digest inference per subscriber; curation-free (no content graph) | Inference fronted for third parties (F4 exposure at its worst); support expectations of an API | ~0 recurring; occasional essay upkeep | ~0 (or €8–15/mo if the demo deploy is kept) |
| **User-acquisition difficulty** | Highest: consumer learners, zero existing audience, no channel named in any sibling doc (§4 A6); vs free lab tutors | High but testable: one shareable artifact (00 §4.2 predicts guided reads are "something a learner would screenshot and share"); launchable on HN/X/Reddit in a week | High: crowded, consolidating market (Elicit/Consensus/Undermind/Scholar Inbox et al., §2.C) but the buyer *is* today's natural user | Highest-friction: cold B2B outreach, solo, no brand | Lowest: distribution *is* the deliverable (posts travel on their own merits) | N/A |
| **Moat / differentiation** | Strong *if* engagement works (relationship + ledger compound); core mentor mechanics being commoditized free by Study/Learning/Guided modes (§2.B) | The genuinely uncontested slice: evidence-grounded guided paper reads — no incumbent, and not what general tutors structurally do | Verifier-stance trust vs funded competitors; weak retention economics (00 §3.7's own critique) | Hardening is real but invisible; capability commoditizing fastest | The discipline story is rare and hard to fake; not a business moat | The artifact's completeness is itself the differentiator |
| **Fit to existing assets** | Very high on machinery (01 §5.1), lowest on operator shape (a service-runner's job, not a builder's) | Highest overall: reuses pipeline, reader surface, evidence store, HITL, cost caps, with zero new infra | Very high: the digest is the product's native output | High on API surface; zero on billing/sales | Total: the assets *are* the content | Total |
| **Downside if it fails** | Months of work + recurring commitments + possibly stranded learners + a diluted portfolio story; sunk identity/email infra (partially salvageable for C) | ~2–4 weeks + small inference spend; the briefings remain portfolio/demo assets regardless | Weeks of work; features still improve the core product | Weeks + possible unpaid inference bills; API polish keeps value | Hours of writing nobody read; repo unharmed | None identifiable |
| **What it proves for a portfolio** | "Attempted an edtech startup" — impressive *only if* it gets traction; unfinished, it reads as scope creep **[judgment]** | "Shipped an AI feature, measured real engagement, made a data-driven call" — a senior-PM/staff-eng story either way the data goes | "Extended a system to production users in its natural market" | "Ran a hardened API in production" (only if real callers exist) | Highest proof-per-hour: the build record made legible, with measured eval numbers | A finished, measured, honest system — already ~95% banked |

Reading the matrix: **B dominates A on every column except
moat-if-engagement-works** — and B is the cheapest possible test of
exactly that column. **E dominates everything under O1.** A is
defensible *only* as a later tranche purchased with B's evidence.

---

## 4. The assumption register — everything the platform bet stands on

Each assumption: how load-bearing (does the bet die if false?), how
cheaply testable, and the current evidence. Ordered by
(load-bearing × untested).

### A1 — Learners engage with an AI mentor when it is the front door
- **Load-bearing**: Total. 00 §4.4 ranks it risk #1; 00 §6.3 defines
  the kill-signal by it (Khanmigo shape: <15% weekly usage,
  outcomes indistinguishable from self-serve).
- **Evidence now**: *Against*: the Khanmigo two-year RCT — engagement,
  not capability, was the binding constraint; ~15% uptake (00 §3.5).
  MOOC base rates: 3.13% completion, 52% never start (Reich &
  Ruipérez-Valiente, Science 2019, via 00 §3.1). *For*: the design
  responses in 00 §4.3 are plausible but untested; "front door, not
  widget" is a hypothesis, not a result.
- **Cheap test**: Yes — and here is this document's sharpest critique
  of the roadmap: 03 measures engagement at Gate LG-2, **after**
  Phase L0 (14 WOs incl. MT-01's six gates) + L1 (16 WOs) + L2's
  scheduler/email (13 WOs). The plan spends ~43 work orders and
  stands up every recurring bill before its own #1 risk produces a
  single data point. §5 inverts this: the wedge (Rung 2) yields
  return-rate data at ~10% of that cost. To 03's credit, RR-L01
  names the risk and LG-2 pre-commits a threshold — the ordering,
  not the honesty, is the flaw.

### A2 — The mentor's differentiation survives the frontier labs
- **Load-bearing**: High. The pitch is "a mentor that reads with
  you"; the market since mid-2025 gives everyone a free mentor.
- **Evidence now**: **This is the vision document's one material
  blind spot.** 00 §3's scan covers Coursera, fast.ai, Brilliant,
  Duolingo, Khanmigo, Papers with Code, Elicit — but not ChatGPT
  Study Mode (free tier, launched 2025-07-29 —
  [Inside Higher Ed](https://www.insidehighered.com/news/tech-innovation/artificial-intelligence/2025/08/07/understanding-value-learning-fuels-chatgpts)),
  Claude Learning Mode with persistent memory
  ([Northeastern guide](https://learning.northeastern.edu/ai-student-guides-using-claude-learning-mode-to-study)),
  or Gemini Guided Learning
  ([category survey](https://www.buildmvpfast.com/articles/best-llms-2026-guide/education-ai)).
  Socratic tutoring, level-adaptation, and months-long memory — three
  of the five rows in 00 §1.3's "why incumbents can't" table — are
  now free defaults from the very vendors whose inference this
  platform would resell at a markup. What survives: guided
  evidence-grounded paper reads, cited living digests, the honest
  ledger, HITL path ownership — the paper-native slice.
- **Cheap test**: Partially — the wedge tests exactly the surviving
  slice. The rest is a standing strategic fact to plan around, not
  test away.

### A3 — The content treadmill is sustainable
- **Load-bearing**: High for the *platform*; low for the wedge.
- **Evidence now**: 02 is admirably honest: ~120–160 h cold start,
  2–4 h/week thereafter, single-reviewer bottleneck (02 Q5), monthly
  rotating "current" slots, link-rot repair, a 30-day YouTube
  metadata clock. That is a permanent editorial job with no
  substitute teacher. No evidence exists about the owner's appetite
  for it.
- **Cheap test**: Yes — the wedge's 8–10 briefings are a direct
  sample of the work: if reviewing 10 briefings once is unpleasant,
  reviewing a queue weekly forever is disqualifying.

### A4 — Per-learner inference economics hold ($3–7/mo daily-active)
- **Load-bearing**: High for any paid/free-tier future.
- **Evidence now**: 01 §6 is carefully built (cached-prefix Haiku
  tutoring, precompute, learning-mode research caps) *and* carries
  its own warning label: the repo's eval harness "has never had a
  funded green campaign... treat unmeasured numbers as hypotheses"
  (01 §7). The estimate is stated as most fragile to turns-per-session
  and context-bloat (01 §6.4), the precompute low end assumes a batch
  API integration that does not exist (01 Q9), and the nightly
  precompute assumes a scheduler that does not exist (01 Q3). The
  willingness-to-pay side ($10–15/mo) has zero evidence.
- **Cheap test**: Yes — instrumented wedge sessions measure real
  turns, real context sizes, real per-session cost through the
  existing accumulator (ADR 0051) with no new code.

### A5 — A solo operator can run this platform
- **Load-bearing**: Total under O2/O3.
- **Evidence now**: None of the sibling docs budgets the operator's
  week. Summing their own line items: 2–4 h content review (02 §5) +
  user support (unbudgeted; MT-01 notes even password-reset load
  under non-C options) + email deliverability ops (03 §4.5, RR-L07)
  + incident response on a first-recurring-bills stack + monthly
  content rotation + the gate cadence 03 §6.6 says will dominate the
  calendar. **[judgment]**: this is 6–10 h/week indefinitely, before
  any growth. The revamp's fleet model parallelizes *build*, not
  *operations* — operations don't fork.
- **Cheap test**: Partially — the pilot rungs sample support load;
  mostly this is a question for the owner's calendar, not for code.

### A6 — Distribution: learners can be acquired at all
- **Load-bearing**: Total under O2/O3. Second only to A1, and less
  acknowledged: A1 at least has a risk-register row; **acquisition
  has no owner, no channel, no budget, and no mention in any of the
  four sibling documents.** 00 §6 sets 7-day/30-day *return* targets
  — every metric starts after arrival. The closest thing to a
  channel is 00 §4.2's hope that sprint briefs get screenshotted.
- **Evidence now**: The repo has zero users, zero audience, no
  mailing list, no public deployment. Base rate for solo side
  projects acquiring consumer users without an audience or budget is
  brutal **[judgment]**.
- **Cheap test**: Yes, the cheapest of all — a landing page +
  waitlist and one honest launch post cost days and directly measure
  pull (§5 Rung 1).

### A7 — Legal/licensing posture holds
- **Load-bearing**: Medium (shapes content strategy; unlikely to
  kill outright because 02's link-out-first posture is conservative).
- **Evidence now**: 02's own repeated caveat: every licensing note
  "needs owner/counsel confirmation." Sleepers named there: OCW's
  NC/SA clause vs any future paid tier, Semantic Scholar's
  non-commercial fields, the YouTube compliance audit if quota
  grows, full-text caching posture at platform scale (02 Q2–Q4).
- **Cheap test**: The wedge sidesteps nearly all of it (arXiv
  metadata CC0, briefings original prose, links out); counsel
  review is only needed before the *platform* tranche.

### A8 — The MT-01 lift lands cleanly, and its costs are accepted
- **Load-bearing**: Total for multi-user anything (01 §0's constraint
  1; 03 §4.1 "scheduled here, first-class").
- **Evidence now**: MT-01 is PROPOSED with blocking questions open
  (Q1–Q3), a spend-cap prerequisite (F4) unshipped, a stable
  owner-id follow-up (F1) forced, CSRF work pulled into L0, six
  sequential gates, and a server resize attached (03 §6.1, OD-2/3/4).
  All plannable; none started; every piece is real work with a real
  bill.
- **Cheap test**: No — identity doesn't prototype meaningfully. The
  correct move is *deferral*: nothing in Rungs 0–2 needs it, which
  is precisely why the ladder front-loads what doesn't.

### A9 — Expert trust survives contact (one-hallucination rule)
- **Load-bearing**: High for the Chen/Aisha wedge personas 00 Q1
  leans toward.
- **Evidence now**: The verifier/evidence machinery exists and is the
  right defense (ADRs 0015–0017), but its measured faithfulness
  numbers **do not exist** — the eval that would produce them is the
  never-funded campaign. The platform's core trust claim is
  currently unmeasured by the repo's own standard.
- **Cheap test**: Yes — fund the eval campaign. Order-$25–75. This
  single spend upgrades A9 *and* A4 *and* the portfolio story, which
  is why it is Rung 0.

---

## 5. The cheap-test ladder

Sequenced so each rung falsifies the biggest *currently untested*
assumption for the least money, and so every rung's artifact retains
value even if the next rung never happens. Percentages are of the
full-platform build (~71 WOs + content + recurring setup).

### Rung 0 — Decide and measure what already exists (~0.5%; days)
1. **Owner answers §1** (objective function) and §6.3's flip
   questions. Costs nothing; gates everything.
2. **Fund the eval campaign** (order-$25–75, the decision 06-polish
   has flagged since the beginning). Tests **A9/A4-adjacent**: the
   platform's trust story finally gets numbers, and the owner's
   willingness to fund *any* recurring-adjacent spend gets its first
   data point. If Rung 0's spend is declined, the honest conclusion
   is that the objective function is O1/O4 and the answer to the
   platform is *no* — recorded, not drifted into.

### Rung 1 — Publish the flagship path, statically (+ a waitlist) (~1–2%; 1–2 weeks)
Build nothing interactive. Publish *"Reading your first papers"* —
02's differentiated path — as a public, static artifact: 8–10 papers,
each with its agent-drafted, human-reviewed briefing companion
(word2vec → attention → Transformer → … → RLHF, per 02 §2.3),
rendered through the existing report surface or plain pages, plus a
one-page description of the mentor vision and a waitlist form. Launch
it once, honestly (HN/X/r-ML). **Tests A6 (distribution/pull) — the
zero-evidence assumption — and samples A3 (is briefing review
tolerable?).** Falsifiable outcome: meaningful traffic + waitlist
signups from one launch, or not. Every briefing produced is
simultaneously wedge content (Rung 2) and portfolio material
(alternative E), so a failed rung still banks its artifacts.

### Rung 2 — The wedge behind the existing UI (~8–12%; 3–5 weeks)
Alternative B in full: interactive guided reads in the Evidence
Workbench, single-user flag mode + ≤5 hand-invited pilot users on
per-principal API keys, instrumented per-session cost, a 14-day
observation window. **Tests A1 on the surviving differentiator (do
invited users return in week 2 without being nudged — a 7-day-return
proxy against 00 §6.1's ≥40% target), A4 with real measured sessions,
and A2's surviving-slice hypothesis.** Pre-commit the threshold
before the pilot, per 03's own OD-12 discipline. No scheduler, no
email, no MT-01, no recurring bills.

### Rung 3 — The platform's first tranche, evidence-priced (~30%; L0 + a thin L1)
Only if Rung 2 clears its pre-committed bar: MT-01/L0 (identity,
spend cap, CSRF, resize — 03 §6.1) plus a *thin* L1 (the content
graph read-only, the wedge's paths as its first content; generation
campaigns per OD-6). **Tests A8 in reality and A1 at cohort scale
(~25–100 invited).** The daily loop — scheduler, email, the entire
L2 — stays unbuilt until *this* rung's cohort shows organic return
behavior, inverting 03's ordering: engagement evidence buys
retention infrastructure, not the reverse. Beyond Rung 3 lies the
plan the sibling documents already wrote, now standing on data.

**The ladder's contract**: each rung has a pre-written outcome that
stops the climb, and stopping at any rung leaves a strictly better
repo than today's (numbers at 0, a published path at 1, a shipped
measured feature at 2, real multi-user infrastructure at 3).

---

## 6. Recommendation

### 6.1 The recommendation

**Do not start the platform build. Climb the ladder: Rung 0 now,
Rung 1 immediately after, Rung 2 (the guided-read wedge) as the next
substantial engineering work — and treat the full platform as a
purchase to be made later with Rung 2's evidence, at most.**
Equivalently: adopt alternative **B** sequenced by §5, hold **A** as
its conditional continuation, and bank **E**'s cheap capstone (the
funded eval + the published path double as portfolio flagships)
along the way.

The reasoning trail, compressed: (1) the owner's objective function
is undetermined, and the repo's revealed preferences (§1.1) point
away from the recurring commitments the platform requires; (2) the
platform's two most load-bearing assumptions — engagement (A1) and
distribution (A6) — have zero product-specific evidence, and the
sibling roadmap's first engagement reading sits ~43 work orders deep
(§4.A1); (3) the mentor's generic differentiators are being
commoditized free by the frontier labs, a fact outside the vision
doc's scan (§4.A2), while the paper-native slice remains genuinely
uncontested — and the wedge *is* that slice, already ranked
differentiator #1 by 00 §4.2 itself; (4) the wedge dominates the
platform on every matrix column except the moat that only engagement
evidence can underwrite (§3); (5) every rung's artifact retains
value under every objective function, so the ladder is
near-regret-free while the platform build is not.

This is a recommendation the owner can reject. The sibling documents
describe a real, buildable, unusually honest product; if the owner's
answer to §1 is "O2, with a multi-year horizon, and I accept the
bills and the operator's week," then Rungs 1–2 are *still* the right
first moves — the disagreement would be only about what happens
after Rung 2, and the evidence will have arrived by then.

### 6.2 The alternatives, ranked under each objective

| Objective | Ranking | One-line why |
|---|---|---|
| **O1 — portfolio** | **F ≥ E > B** > D > C > A | Finish and make legible; the wedge adds one demoable, measured feature; the platform dilutes a completed story |
| **O2 — real users** | **B > C > A** > D > E > F | Cheapest engagement evidence first; the natural existing user second; the platform only as B's funded continuation |
| **O3 — revenue** | **C > A > D** > B > E > F — with the honest caveat that plausibly *none* clears an opportunity-cost bar for a solo operator **[judgment]** | Researcher tools have demonstrated willingness-to-pay; consumer learning has demonstrated cost |
| **O4 — learning-by-building** | **B > A > D** > C > E > F, capped at Rung 3 with no recurring commitments | Maximize new problem shapes; never acquire learners you plan to abandon |

That B is top-two under three of four objectives — and the platform
is top-two under none without qualification — is the matrix's
strongest single result.

### 6.3 The questions whose answers would flip this

1. **The objective function (§1).** If the owner answers "O2/O3 with
   a multi-year commitment and explicit acceptance of recurring
   bills and a 6–10 h/week operator load," the recommendation's
   *destination* flips from "wedge, then decide" toward "wedge as
   Phase 0 of the committed platform" — the first two rungs do not
   change, but Rung 3 becomes a plan rather than an option.
2. **Rung 1–2 evidence.** A strong pull signal (waitlist conversion,
   unprompted sharing, pilot users returning in week 2 at or above
   the pre-committed threshold) flips the platform from "not now" to
   "buy the next tranche"; a Khanmigo-shaped result flips this
   document's residual platform option to a recorded *no* under 00
   §6.3's own kill rule.
3. **A credible distribution asset appearing.** If the owner builds
   or reveals an audience (a successful E-style launch, an existing
   community, a partner channel), A6 stops being the second-biggest
   untested assumption and the platform's expected value rises more
   than any engineering result could raise it.

A fourth, honorable mention: if the frontier labs ship *paper-native
guided reading* (not generic tutoring) as a free default, the wedge's
uncontested slice closes and alternatives C/E/F become the whole
menu. Watch for it; don't wait for it.

---

## 7. Source index

**Repo grounding**: [`README.md`](../../README.md) (system shape,
test counts, eval status: 54/54 nightly failures, no funded
campaign), [`docs/architecture.md`](../../docs/architecture.md),
[`docs/revamp/STATUS.md`](../../docs/revamp/STATUS.md) (Gate 4
closed; reserved-for-user list),
[`docs/proposals/README.md`](../../docs/proposals/README.md)
(proposal discipline),
[`docs/proposals/multi-tenancy.md`](../../docs/proposals/multi-tenancy.md)
(MT-01, F1/F4, options A/B/C, gates MT-A…F),
[`planning/06-portfolio-polish.md`](../06-portfolio-polish.md)
(the resume-artifact charter and 90-second experience),
[`planning/05-agentic-upgrade-plan.md`](../05-agentic-upgrade-plan.md)
(the "interview framing" block; deferred skills registry),
[`planning/02-feature-ideas.md`](../02-feature-ideas.md) (ideas
15/21/25/27/28/29/30/31/32),
[`planning/01-enterprise-gaps.md`](../01-enterprise-gaps.md)
(webhooks/audit/RBAC/DLQ still open),
[`planning/README.md`](../README.md),
[`docs/revamp/06-WORK-ORDERS.md`](../../docs/revamp/06-WORK-ORDERS.md)
(WO sizing convention).

**Sibling numbers relied on**: 00 §3.1/§3.5/§3.8/§4.2/§6 (3.13% MOOC
completion and 52% never-start — Reich & Ruipérez-Valiente,
[*The MOOC Pivot*, Science 2019](https://www.science.org/doi/10.1126/science.aav7958);
Khanmigo two-year RCT ~15% usage / engagement-bound —
[trial summary](https://www.winssolutions.org/khanmigo-ai-tutoring-two-year-trial/),
[Khan Academy writeup](https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/);
differentiator ladder; metric targets and kill-signal); 01
§5.2/§6.4/§6.5/§7 ($3–7/mo daily-active, $1.50–4 realistic,
$0.50–1.20 free tier; 6–9 engineering weeks; "treat unmeasured
numbers as hypotheses"); 02 §2.3/§5 (~120–160 cold-start hours,
2–4 h/week maintenance, 3 flagship paths, licensing caveats); 03
§1/§2.8/§6 (~71 WOs ±20%, 11 gates, 2.5–3× revamp, first recurring
bills, LG-2 as the engagement gate, RR-L01–L10, OD-1–12).

**External, checked 2026-08-29**:

- ChatGPT Study Mode launch and framing —
  [Inside Higher Ed, 2025-08-07](https://www.insidehighered.com/news/tech-innovation/artificial-intelligence/2025/08/07/understanding-value-learning-fuels-chatgpts);
  [Learn & Work Ecosystem Library entry](https://learnworkecosystemlibrary.com/initiatives/chatgpt-study-mode/)
- Claude Learning Mode as a study default —
  [Northeastern University student guide](https://learning.northeastern.edu/ai-student-guides-using-claude-learning-mode-to-study)
- The 2026 "labs compete on pedagogy; the teaching version is
  increasingly free" framing, incl. Gemini Guided Learning —
  [buildmvpfast education-AI category survey](https://www.buildmvpfast.com/articles/best-llms-2026-guide/education-ai)
- Crowded research-assistant category (Elicit, Consensus, SciSpace,
  Undermind, scite, STORM) —
  [listenlabs 2026 category overview](https://listenlabs.ai/articles/top-ai-research-assistant-2026/);
  [Elicit-alternatives roundup](https://www.atlasworkspace.ai/blog/elicit-alternatives)
- Free personalized paper-alert tooling —
  [Scholar Inbox](https://www.scholar-inbox.com/)
  ([arXiv:2504.08385](https://arxiv.org/html/2504.08385v1))
