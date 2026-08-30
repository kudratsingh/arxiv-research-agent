# Learning platform — vision and users (00)

> ## ⚠ STATUS: PROPOSED
>
> **Nothing in this document is approved, decided, or implemented.**
> This is the vision and user document for evolving
> `arxiv-research-agent` from a research-question tool into an AI/ML
> learning platform. It follows the repo's proposal discipline
> ([`docs/proposals/README.md`](../../docs/proposals/README.md)): a
> human decision gate sits between this document and any code. The
> open questions in [§8](#8-open-product-questions-for-the-owner) are
> that gate's agenda.

- **Workstream**: LP-00
- **Date**: 2026-08-29
- **Decider**: kudratsingh — **pending**
- **Companion documents** (each owned separately; referenced here by
  name, not written here): `01-LEARNING-AGENT.md` (the mentor agent's
  design), `02-CONTENT.md` (courses, curation, and sourcing),
  `03-ARCHITECTURE-ROADMAP.md` (system architecture and sequencing)
- **Builds on**: the shipped Evidence Workbench and its design
  language ([`docs/revamp/03-DESIGN-BRIEF.md`](../../docs/revamp/03-DESIGN-BRIEF.md)),
  the LangGraph research pipeline ([`docs/architecture.md`](../../docs/architecture.md)),
  the dormant identity model ([`docs/proposals/multi-tenancy.md`](../../docs/proposals/multi-tenancy.md)),
  and the unscheduled idea backlog ([`planning/02-feature-ideas.md`](../02-feature-ideas.md)
  — ideas 15, 21, 27, 28 are ancestors of this document)

Every claim below is grounded in this repo, cited to a source checked
on the stated date, or explicitly marked **[judgment]**.

---

## 1. Thesis

### 1.1 What we already have that no learning platform has

This system, on `main` today, does four things that are individually
rare and jointly unique:

1. **It reads the literature, live.** The pipeline searches arXiv,
   optionally walks Semantic Scholar's citation graph, reads full
   paper text, and synthesizes a cited briefing
   (`src/graph/workflow.py`; README §Architecture). Its raw material
   is the field as of this morning, not a curriculum filmed two years
   ago.
2. **It runs long, multi-step plans with a human in the loop.** Every
   run pauses at a plan the human reviews, edits, and approves before
   anything is spent (ADR 0030; `enable_hitl` on by default). The
   machinery for "propose a plan, let the human own it, then execute
   it over time" is not a mockup — it is the product's signature
   interaction.
3. **It knows what it knows.** The evidence store grounds claims in
   specific source chunks and a verifier judges faithfulness at
   runtime (ADRs 0015–0017). The design brief generalized this into
   the product's epistemic stance: *report what was witnessed, state
   plainly what was not, never interpolate*
   ([`03-DESIGN-BRIEF.md` §0](../../docs/revamp/03-DESIGN-BRIEF.md)).
4. **It accounts for every dollar.** Per-run cost tracking, per-agent
   model routing, prompt caching, and hard cost caps are shipped and
   enforced at a single choke point (ADRs 0021, 0022, 0051). A
   consumer product built on paid inference dies without exactly this
   discipline.

### 1.2 The thesis

**A mentor that reads with you.** The learning platform turns the
research agent's capabilities inward: instead of answering *"what
does the literature say about X?"*, it answers *"who do I need to
become, and what should I do today to get there?"* — and then walks
the road alongside the learner, daily, for months.

Concretely, the agent that today plans a literature search becomes an
agent that plans a **learning path**: it interviews the learner about
goals, current skills, and academic level; proposes a long-horizon
plan the learner reviews and approves exactly the way they approve a
research plan today; then decomposes that plan into daily sessions —
a curated video, a guided paper read, a synthesized lesson, a
retrieval quiz — and adapts the plan as evidence about the learner
accumulates. The mentor's lessons cite their sources because the
pipeline that writes them already does. Free courses and curated
video/paper tracks are the library; the mentor is the librarian,
tutor, and coach in one. (The mentor's internal design is
`01-LEARNING-AGENT.md`; the content pipeline is `02-CONTENT.md`.)

### 1.3 What is uniquely possible here that Coursera and YouTube playlists cannot do

| Capability | Why incumbents can't | Why we can |
|---|---|---|
| **Lessons that track the field** | Filmed curricula freeze at production time; re-filming is the dominant content cost | The synthesis pipeline compiles a cited lesson from this week's papers on demand — the marginal unit of content is an LLM run, not a film crew |
| **Reading real papers, guided** | MOOCs stop at textbook abstractions; paper-reading is the un-taught skill that gates every ML career | The reader agent already parses, chunks, ranks and extracts evidence from any arXiv PDF; a "read this with me" session is a re-skinning of machinery on `main` |
| **A plan the learner owns** | Platforms assign fixed syllabi; personalization means a recommender reordering a catalog | HITL plan review is our signature interaction — the learner edits and approves their own path, and the run "goes nowhere until someone approves" is already how the system thinks (README §HITL) |
| **Honest progress** | Progress = videos watched; certificates attest attendance | The evidence/verifier stance applied to mastery: the ledger records what the learner *demonstrated*, marks what was never observed, and lets knowledge visibly decay ([§5.4](#54-surface-4--the-progress-ledger)) |
| **A mentor with memory across months** | Course forums and AI "coaches" are stateless per-course bolt-ons | Conversations, checkpoints, and prior-context retrieval are shipped storage concerns (ADR 0032; storage matrix in `docs/architecture.md`) — long-horizon memory is a schema extension, not a new system |

### 1.4 What this is not

- **Not a MOOC.** No cohort calendars, no filmed lecture catalog, no
  certificate mill. Courses exist ([`02-CONTENT.md`]) but they are the
  map, not the journey.
- **Not a chatbot tutor bolted onto a catalog.** The Khanmigo result
  ([§3.5](#35-khan-academy--khanmigo)) is the cautionary tale: an AI
  tutor waiting politely inside someone else's product gets used by
  15% of the students who have it. The mentor here *is* the product's
  front door, not a widget on it.
- **Not a gamified habit app wearing an education costume.** Adult
  learners with real goals are the audience; the retention design
  ([§4.3](#43-motivation-decay--respectful-retention)) is built on
  their agency, not their anxiety.

---

## 2. Personas and jobs-to-be-done

Five personas, ordered roughly by how well the existing system
already serves their neighbors. Each is concrete enough to test copy
and surfaces against. **[judgment]** throughout — these are design
hypotheses to validate, not user research findings; the repo has no
user base to study (the deployed product is a single shared
workspace, [`multi-tenancy.md` §1.2](../../docs/proposals/multi-tenancy.md)).

### 2.1 Priya — CS undergrad prepping for a first ML internship

- **Situation**: third-year CS student, strong at coursework, six
  months from internship interviews. Knows calculus and Python;
  has never read a paper end-to-end.
- **Pain today**: the gap between "took the ML elective" and "can
  discuss attention variants in an interview" is bridged by a chaotic
  mix of YouTube, blog posts, and half-finished Coursera
  specializations. No one tells her what to skip.
- **On the platform, weekly**: a goal ("ready for ML internship
  interviews by February"), a path she approved, ~4 sessions/week of
  25–40 minutes: one guided paper read, two concept lessons with
  retrieval quizzes, one implementation prompt.
- **Comes back tomorrow because**: the mentor's morning note names
  exactly one next thing, sized to fit before her 10am class — and
  yesterday's quiz told her honestly which of her three shaky
  concepts decayed.
- **Quits if**: sessions feel like a textbook chapter got pasted into
  a chat window; or the path never visibly shortens as the deadline
  approaches; or a quiz claims she "mastered" something she knows she
  guessed.

### 2.2 Marcus — working backend engineer transitioning into ML

- **Situation**: eight years of production engineering, evenings and
  one weekend morning available, employer will not pay for a degree.
- **Pain today**: every "learn ML" resource assumes either a
  student's free time or a beginner's blank slate. He doesn't need
  Python taught; he needs the shortest defensible route from
  "can ship services" to "can ship models", and proof of progress he
  can show a hiring manager.
- **On the platform, weekly**: 3 sessions of ~45 minutes, biased
  toward building; a path that explicitly credits what he already
  knows (the intake interview is where skills-awareness earns its
  keep); a monthly path review where he renegotiates scope with the
  mentor.
- **Comes back tomorrow because**: his time is the scarcest of any
  persona, and the mentor demonstrably spends it well — every session
  ends by naming what it advanced, in the plan he approved.
- **Quits if**: the path pads itself with prerequisites he's already
  demonstrated; or a missed week greets him with guilt mechanics
  instead of a replanned path; or progress is unshareable.

### 2.3 Dr. Chen — researcher keeping up with a subfield

- **Situation**: postdoc in NLP, current on her own niche, drowning
  in adjacent ones. Already the natural user of the research side of
  this product.
- **Pain today**: "keeping up" tools (feeds, alerts, Elicit-style
  extraction) hand her *more* reading, not more understanding. What
  she wants is a standing brief: what moved in mechanistic
  interpretability this month, and which two papers deserve her
  hours.
- **On the platform, weekly**: a standing "keep current" path per
  subfield; a weekly synthesized digest (a briefing — the pipeline's
  native output) plus one guided deep-read; occasional gap-fill
  lessons when a digest exposes a method she never learned.
- **Comes back because**: the digest cites everything and admits
  coverage gaps (the verifier stance), so it is the one summary she
  can trust professionally; and research threads and learning paths
  live in the same rail — she is already here to run queries.
- **Quits if**: digests hallucinate or flatten nuance once; her
  trust does not survive a second offense. **[judgment]** — but the
  entire evidence/verifier investment (ADRs 0015–0017) exists because
  this failure mode is fatal for expert users.

### 2.4 Sam — self-taught beginner

- **Situation**: no CS degree, career in an unrelated field, pulled
  in by the AI wave. High enthusiasm, high churn risk, weakest prior
  scaffolding.
- **Pain today**: the internet offers Sam either hype (threads,
  shorts) or cliffs (fast.ai assumes a year of coding; Coursera's
  math walls). The 52%-never-start / ~3%-complete MOOC funnel
  ([§3.1](#31-coursera--deeplearningai)) is mostly made of Sams.
- **On the platform, daily**: a deliberately tiny daily session
  (10–15 min) — curated video plus one retrieval check; a path whose
  first approved milestone is honest ("in 8 weeks you will train and
  explain a small classifier", not "become an AI engineer").
- **Comes back tomorrow because**: the daily unit is small enough to
  never skip, and the mentor's tone treats him as an adult with a
  goal, not a streak to farm.
- **Quits if**: he hits an unmarked prerequisite cliff; or the free
  tier's limits land mid-session with no warning (spend must be
  disclosed *before* the click — principle P2 of the design brief,
  inherited unchanged); or the content condescends.

### 2.5 Aisha — ML engineer who needs depth on demand

- **Situation**: already employed in ML; learning is bursty and
  deadline-driven — "I need to actually understand speculative
  decoding by Thursday's design review."
- **Pain today**: search returns either 90-second explainers or the
  raw paper. Nothing in between adapts to what she already knows.
- **On the platform, bursty**: no standing path; she opens a
  **sprint** — a 3-day micro-path the mentor compiles from the
  actual papers, calibrated by a two-minute intake ("rate your
  familiarity with these five ideas").
- **Comes back because**: sprints respect her existing knowledge and
  cite sources she can bring to the review; each sprint quietly
  extends her skill profile, so the next one starts smarter.
- **Quits if**: intake takes longer than reading the paper would
  have; or the sprint recycles generic content that ignores her
  stated level.

### 2.6 What the personas jointly demand

- One **intake** good enough to place all five without insulting any
  (owned by `01-LEARNING-AGENT.md`).
- **Session sizes from 10 to 45 minutes** — the daily unit is a
  variable, not a constant.
- **Replanning as a first-class verb** — every persona's quit
  condition involves the plan failing to bend to reality.
- **Per-user identity.** Nothing above works in a shared workspace
  where everyone owns everything. The learning platform converts
  MT-01 from a dormant proposal into a prerequisite
  ([§8](#8-open-product-questions-for-the-owner), Q3).

---

## 3. Competitive and analog scan

Each entry: what it is, the one mechanic worth stealing, the one
failure worth avoiding. Sources checked 2026-08-29 via web search;
key citations inline.

### 3.1 Coursera / DeepLearning.AI

The reference MOOC stack: 183M registered learners as of Q2 2025,
with a tripled generative-AI catalog and an AI "Coach" credited with
~10% higher quiz pass rates
([Coursera Q2 2025 earnings](https://www.marketbeat.com/earnings/reports/2025-7-24-coursera-inc-stock)).
DeepLearning.AI's Deep Learning Specialization has 1M+ learners
([deeplearning.ai](https://www.deeplearning.ai/specializations/deep-learning)).

- **Steal**: Andrew Ng-style **ruthless scoping** — each course names
  exactly what you'll be able to do at the end, and the specialization
  structure gives a legible ladder. Our path milestones should read
  like DeepLearning.AI course outcomes, not like syllabi.
- **Avoid**: **completion theater**. The definitive study of the model
  — Reich & Ruipérez-Valiente, *The MOOC Pivot*, Science 2019,
  565 MIT/Harvard edX courses, 12.67M registrations — found 3.13%
  completion in 2017–18, declining year over year, with 52% of
  registrants never starting
  ([Science](https://www.science.org/doi/10.1126/science.aav7958);
  [Inside Higher Ed summary](https://www.insidehighered.com/digital-learning/article/2019/01/16/study-offers-data-show-moocs-didnt-achieve-their-goals)).
  A certificate-shaped finish line divorced from the learner's actual
  goal produces enrollment, not learning.

### 3.2 fast.ai

The most respected free ML course, built on the "whole game"
pedagogy: lesson one trains a working state-of-the-art model, then
the course digs down into why
([Jeremy Howard](https://x.com/jeremyphoward/status/1296884279784255488);
[why the top-down approach works](https://bhatta.io/2018/10/20/why-i-advocate-fast-ai-top-down-approach/)).

- **Steal**: **top-down sequencing**. Every path here should reach a
  working artifact or a real paper inside week one; theory arrives on
  demand, justified by something the learner already touched.
- **Avoid**: **the cliff after the course**. fast.ai is a brilliant
  fixed artifact with no ongoing relationship — when the course ends,
  so does the guidance, and its assumed coding fluency is exactly the
  unmarked prerequisite that ejects Sam ([§2.4](#24-sam--self-taught-beginner)).
  The mentor's whole premise is that guidance persists between and
  beyond courses.

### 3.3 Brilliant

Interactive problem-first learning; no video lectures, every lesson
is a sequence of manipulations and questions
([brilliant.org](https://brilliant.org/help/why-brilliant)).

- **Steal**: **interaction before explanation**. Brilliant's core bet
  — that doing beats watching — matches the learning-science evidence
  for retrieval practice ([§3.8](#38-the-learning-science-floor)).
  Our sessions should lead with a question, not a paragraph.
- **Avoid**: **shallowness at the advanced end**. Reviews repeatedly
  flag that depth thins out beyond the polished intro tiers,
  especially in newer CS/data content
  ([SkillScouter review](https://skillscouter.com/brilliant-review-math-science-coding/);
  [user critiques](https://brighterly.com/blog/is-brilliant-org-worth-it/)).
  Our depth ceiling is the literature itself — the platform must
  visibly hand advanced learners real papers rather than running out
  of runway.

### 3.4 Duolingo — the habit-mechanics reference

The most successful consumer learning habit machine; streaks,
leaderboards, and loss-aversion mechanics built a business measured
in daily active users
([gamification teardown](https://trophy.so/blog/duolingo-gamification-case-study);
[retention analysis](https://vmobify.com/blog/how-duolingo-grew)).

- **Steal**: **the tiny daily unit**. Duolingo's deepest insight is
  not streaks — it is that the atomic session is small enough that
  "not today" is never rational. Our daily check-in must fit in ten
  minutes and never *require* more.
- **Avoid**: **anxiety as a retention engine**. Streak mechanics run
  on loss aversion; pushed hard they produce compulsive checking and
  guilt-driven engagement that critics class with social-media dark
  patterns, and Duolingo itself had to cap reminders after user
  backlash ([criticism survey](https://www.uladshauchenka.com/p/duolingo-case-study-the-gamification);
  [StriveCloud analysis](https://www.strivecloud.io/blog/gamification-examples-boost-user-retention-duolingo)).

What separates respectful from manipulative retention for adult
learners — the standard this product adopts (**[judgment]**, but a
direct extension of the design brief's honesty principles):

1. **Measure learning, not opens.** A streak of app-opens is a vanity
   loop; continuity of *demonstrated retention* (quiz performance
   over spaced intervals) is the thing worth keeping unbroken.
2. **The learner sets the contract.** Cadence is chosen at path
   approval ("3 sessions/week") and the mentor holds the learner to
   *their own* commitment — accountability to a self-authored plan,
   not to a mascot's feelings.
3. **Pause without penalty.** Life happens; the correct response to a
   missed week is a replanned path, not a broken chain. Duolingo
   sells streak-freezes — monetizing the anxiety it created. We give
   the pause away.
4. **Notifications state facts, not guilt.** "Your review of
   attention mechanisms is due — 10 minutes" is respectful;
   "Priya, you're about to lose everything" is not.

### 3.5 Khan Academy / Khanmigo

Mastery learning at scale, now with an LLM tutor. The most important
— and most sobering — analog. A two-year randomized trial of
Khanmigo found math gains of ~1.26 national percentile ranks per
term, *comparable to Khan Academy practice without AI*, and
identified **student engagement, not model capability, as the
binding constraint**; only ~15% of students with access actually
used the tutor
([trial summary](https://www.winssolutions.org/khanmigo-ai-tutoring-two-year-trial/);
[Khan Academy's own product-test writeup](https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/)).

- **Steal**: **mastery gates and prerequisite awareness**. Khan's
  discipline of checking prerequisites before advancing — recently
  extended so the tutor adapts to prior mastery — is the correct
  skeleton for the progress ledger.
- **Avoid**: **the optional tutor**. Khanmigo waited politely in a
  corner of someone else's workflow and was ignored by 85% of its
  audience. The mentor cannot be a feature the learner must remember
  to invoke; the daily check-in *is* the front door. This finding is
  also the biggest risk to this entire proposal — see
  [§4.4](#44-the-honest-risk-register).

### 3.6 Papers with Code (shut down 2025)

The paper↔code↔benchmark index, shut down by Meta on 2025-07-25;
Hugging Face hosts a partial successor and a static community mirror,
and researchers widely lament the loss of task-level SOTA tracking
([HyperAI news](https://hyper.ai/en/news/42900);
[Coursera explainer](https://www.coursera.org/articles/papers-with-code);
[redirect issue](https://github.com/paperswithcode/paperswithcode-data/issues/116)).

- **Steal**: **the paper–artifact link as a learning object**. "Here
  is the paper, here is the code, here is the benchmark" is the best
  scaffold ever built for guided paper-reading, and its shutdown left
  a genuine gap our guided-read sessions can partially fill
  (`02-CONTENT.md` owns how far to go).
- **Avoid**: **single-sponsor infrastructure**. A beloved resource
  died because one company stopped paying. Any curation layer we
  build must degrade gracefully to primary sources (arXiv itself),
  which — usefully — is where our pipeline already lives.

### 3.7 Elicit and the Semantic Scholar-adjacent tools

AI research assistants for systematic search, screening, and
extraction: Elicit searches 138M+ papers and publishes strong recall
and screening-sensitivity numbers alongside honest third-party
caveats on extraction accuracy
([Elicit review](https://manusights.com/blog/is-elicit-worth-it);
[alternatives survey](https://papersflow.ai/blog/best-elicit-alternatives-2026)).

- **Steal**: **transparent extraction** — every extracted claim
  carries its supporting quote. This is our evidence store's
  worldview validated as a market feature; lessons must inherit it.
- **Avoid**: **tool-without-a-relationship**. Elicit is consulted at
  paper-writing time and then closed; it owns a task, not a
  trajectory. The learning platform's economics
  ([§6](#6-success-metrics)) only work if the relationship is the
  product.

### 3.8 The learning-science floor

Not a competitor — the constraints any honest design must satisfy:

- **Tutoring works, but Bloom's 2-sigma is folklore.** The famous
  claim has never replicated; a 2020 meta-analysis of 96 tutoring
  studies averaged ~0.37 SD, and credible modern estimates for strong
  interventions sit between 0.2 and 0.8 SD
  ([Education Next](https://www.educationnext.org/two-sigma-tutoring-separating-science-fiction-from-science-fact/);
  [Nintil systematic review](https://nintil.com/bloom-sigma/)). Any
  pitch promising 2-sigma results from an AI mentor is marketing
  malpractice; ~0.3–0.5 SD would already be transformative at
  self-serve prices.
- **Spaced retrieval is the highest-confidence mechanic in the
  field.** Distributed practice and practice testing top the
  effectiveness rankings across hundreds of studies
  ([Nature Reviews Psychology 2022](https://www.nature.com/articles/s44159-022-00089-1);
  Hattie & Donoghue's synthesis of 242 studies). The daily check-in
  is therefore built around spaced retrieval, not around content
  consumption — the quiz is the workout; the lesson is the warm-up.

---

## 4. The differentiator ladder

### 4.1 Table stakes — necessary, attracts no one

Course catalog and search; video playback; progress indication;
mobile-usable layout; dark mode; export; account and data deletion.
The Evidence Workbench redesign already supplies the shell, tokens,
a11y discipline, and 390px viability (README §The web UI) — the
table stakes are cheaper here than for a greenfield product, but
they are still just table stakes.

### 4.2 The ladder, ranked by attraction power

**[judgment]** — this ranking is the document's central bet and the
first thing user contact should test.

1. **"A mentor that reads with you."** Guided reads of real papers,
   compiled for *your* goal at *your* level, citing everything. No
   incumbent offers this; it is the shortest line from our shipped
   machinery to something a learner would screenshot and share. The
   acquisition story is Dr. Chen and Aisha showing a colleague a
   sprint brief that would have taken them a day to assemble.
2. **A plan you own, that bends.** Long-horizon path proposal +
   learner approval + continuous replanning. Emotionally, this is
   the anti-MOOC: the platform commits to *your* goal, not you to
   *its* syllabus. Mechanically, it is HITL plan review — our
   signature interaction — pointed at a longer horizon.
3. **Honest progress.** A ledger of demonstrated skills with visible
   decay, and a mentor that never claims mastery it didn't witness.
   Slow-burn differentiation: it converts the epistemic stance expert
   users already trust into the reason career-changers trust their
   own progress enough to put it in front of a hiring manager.
4. **Living content.** Lessons and digests synthesized from the
   current literature. Genuinely unique, but it *retains* more than
   it *attracts* — its value compounds after months of use.
   Positioning it as differentiator #1 would over-promise, because
   for beginner material (Sam, early Priya) curated evergreen content
   beats fresh synthesis anyway (`02-CONTENT.md`).
5. Below the line: streak-like continuity, community features,
   certificates. Deliberately not differentiators — see §3.4, §3.1,
   and Q8/Q9 in §8.

### 4.3 Why learning platforms die — and what this design does about each

**Death by content cost.** Filmed catalogs cost fortunes to make and
rot immediately (§3.1's incumbents spend their margin here; Papers
with Code died when its sponsor stopped paying, §3.6). *Response*:
the marginal content unit is an agent run over open-access papers
plus curation of freely watchable video — the cost structure is
inference + curation time, both metered by machinery this repo
already ships (cost accumulator, model routing, caching — ADR 0021/
0022/0051). The honest residue: inference cost scales with active
learners, which is why §6 makes cost-per-active-learner a first-class
metric and why the F4 global spend cap from
[`multi-tenancy.md`](../../docs/proposals/multi-tenancy.md) is a
launch prerequisite, not hardening.

**Death by completion collapse.** 3–6% MOOC completion (§3.1) is what
happens when the unit of commitment is a 40-hour course chosen in a
moment of enthusiasm. *Response*: the unit of commitment is a
learner-authored goal with mentor-negotiated scope; milestones are
1–3 weeks; paths shrink honestly when time shrinks. We measure
goal-completion, not course-completion, and expect to be judged on
it (§6.2).

**Death by motivation decay.** Enthusiasm has a half-life; platforms
respond with either nothing (MOOCs) or manipulation (§3.4). *Response*:
the respectful-retention contract of §3.4 — learner-set cadence,
fact-based reminders, penalty-free pause, replanning as the default
response to absence — plus a daily unit small enough to survive a bad
week. The wager **[judgment]**: for adults with real goals, an agent
that visibly keeps its promises retains better than an owl that
threatens sadness. If that wager is wrong, we will see it in the
7/30-day return numbers and must resist the dark-pattern ratchet.

**Death by tutor neglect.** The Khanmigo datum (§3.5): capable AI
tutoring, offered as an optional feature, went 85% unused.
*Response*: the mentor is the front door, not a sidebar; the daily
check-in opens with the mentor's note; there is no mentor-less mode
to fall back into.

### 4.4 The honest risk register

1. **Engagement, not capability, is the binding constraint** (§3.5).
   The single biggest risk to the whole idea. Everything in §5 is
   designed against it, and §6's kill-signal is defined by it.
2. **Unit economics of free.** Free courses + paid inference is a
   money pump until the free tier is carefully bounded (Q4, Q5).
3. **Two products, one shell.** Research tool and learning platform
   could blur into dashboard soup; §5.5 is the defense.
4. **Identity is unbuilt.** Everything here presumes per-user
   accounts; MT-01 is PROPOSED and its spend-cap prerequisite (F4)
   is unshipped. Sequencing is a real cost (Q3).
5. **Trust is one hallucination deep** for expert personas (§2.3).
   The evidence/verifier stance must extend to every lesson surface,
   or Dr. Chen leaves and takes the credibility story with her.

---

## 5. UX pillars — extending the Evidence Workbench

The platform inherits the design brief's principles wholesale — spend
disclosed before the click, nothing simulated, observed vs.
not-observed never interpolated, one calm reading surface — and its
token system, shell, and lexicon discipline. Four surfaces, described
as what the user sees and feels; layout mechanics and implementation
belong to `03-ARCHITECTURE-ROADMAP.md`.

### 5.1 Surface 1 — Today (the daily check-in)

The signed-in front door for anyone with an active path. One calm
column, three things, in order:

1. **The mentor's note** — two sentences, specific, written from the
   ledger and the plan: *"Yesterday you demonstrated the KV-cache
   idea. Today: 12 minutes — a retrieval warm-up on attention
   variants, then the first half of a guided read of the FlashAttention
   paper."* Never a dashboard, never a wall of cards.
2. **The session** — one primary action, sized in minutes, honestly.
   The retrieval warm-up leads (§3.8: the quiz is the workout).
3. **The out** — a visible, penalty-free "Not today — replan"
   affordance. The pause is a first-class button, not a hidden
   setting, because §3.4's contract has to be legible to be believed.

Feel: the landing composer's calm, pointed at continuation instead of
initiation. The existing composer remains the front door for anyone
arriving with a research question or no path.

### 5.2 Surface 2 — The Path

The long-horizon plan, rendered with the plan editor's DNA: the goal
at top in the learner's own words; milestones as editable rows;
today's position marked. Two moments matter:

- **Path review** — the intake interview ends with a proposed path
  the learner edits and approves before anything begins, visually and
  mechanically kin to plan review (editable rows, add/remove, one
  unambiguous approve action — brief §P3). The platform's deepest
  habit — *the human owns the plan* — carries over intact.
- **Replanning** — after absence, after a milestone lands early or
  late, or on demand. A replan is presented as a diff against the
  approved path ("two weeks compressed; the RL detour dropped —
  here's why"), which the learner again approves. The path never
  silently rewrites itself.

The checkpoint-spine idea recurs at path scale: milestones the
learner completed are *observed*; future ones are plainly *not yet
observed*; nothing shows a percentage that pretends to know the
future (brief §P1).

### 5.3 Surface 3 — The Lesson Reader

Lessons render where briefings render today: the serif reading
column, section rail, sources attached. Three lesson modes, one
surface:

- **Synthesized lesson** — a cited explainer compiled for this
  learner's level; its metrics strip shows sources used and recency,
  extending the run-metrics honesty to content.
- **Guided read** — the paper itself in the reading column, the
  mentor in the margin: what to read closely, what to skim, a
  comprehension check at section boundaries. This is the flagship
  session type (§4.2 #1).
- **Curated video** — embedded player, the mentor's framing above
  ("watch for how he motivates the loss"), a retrieval check after.

Every lesson ends the same way: one honest line about what this
session advanced in the path, and the retrieval check that will
resurface later, spaced.

### 5.4 Surface 4 — The Progress Ledger

The learner's record, built on the evidence store's worldview:

- Skills appear with the **evidence** that demonstrated them — which
  check, which date, which artifact.
- Retention **decays visibly**: *"Demonstrated 2026-09-03 · not
  reviewed in 21 days"* is a truthful state with a one-tap remedy,
  not a shame badge.
- What was never assessed is **marked unobserved**, not guessed at.
- The ledger is exportable (the export pipeline exists — ADR 0031):
  Marcus's shareable proof of progress falls out of honesty rather
  than a certificate program.

### 5.5 The anti-dashboard-soup rule

One shell, one rail, one object family. Research threads and
learning paths share the existing rail; a path is a long-lived thread
with a goal; a lesson *is* a briefing; a path review *is* a plan
review. The lexicon extends — it does not fork:

| Concept | We say | We never say |
|---|---|---|
| The long-horizon commitment | **Goal** | Objective, OKR, journey |
| The approved sequence toward it | **Path** | Curriculum, syllabus, track |
| One sitting's work | **Session** | Lesson plan, task, unit |
| The daily surface | **Today** | Dashboard, home, feed |
| A demonstrated capability | **Demonstrated** | Mastered, completed, unlocked |
| The record of demonstration | **Ledger** | Profile, XP, stats |
| Spaced-retrieval continuity | **Review due** | Streak, chain, freeze |

Rule stated so it can be enforced: **no new top-level surface beyond
Today, Path, Reader, Ledger without retiring one.** Courses browse
inside the Reader's world; settings stay settings. The moment the
shell needs a second row of navigation, the design has failed this
section.

---

## 6. Success metrics

Honest baselines first, targets second, and one kill-signal.
Industry baselines are cited where a citation exists; targets are
**[judgment]**.

### 6.1 The metric hierarchy

| Metric | Definition | Industry baseline | Our target (12 mo. post-launch) |
|---|---|---|---|
| **Weekly active learners (WAL)** | Completed ≥1 session this week | MOOC platforms don't report comparably; consumer edu DAU/MAU commonly ~10–20% **[judgment]** | North star; absolute number set by Q1/Q2 answers |
| **7-day return** | New learners completing a session 7 days after their first | 52% of MOOC registrants never start at all ([Science 2019](https://www.science.org/doi/10.1126/science.aav7958)) | ≥40% — the intake + first session must earn day 7 |
| **30-day return** | Still active in week 4 | Consumer learning apps retain ~5–10% at day 30 **[judgment]** — widely-repeated industry lore; treat as directional | ≥25% for learners who approved a path |
| **Goal completion** | Approved paths reaching their goal (incl. renegotiated scope) | MOOC completion 3.13% ([Science 2019](https://www.science.org/doi/10.1126/science.aav7958)) | ≥30% — defensible only because goals are learner-sized (§4.3) |
| **Retention of learning** | Spaced-retrieval performance ≥30 days after demonstration | Spaced retrieval is the best-evidenced mechanic ([Nature Rev. Psych. 2022](https://www.nature.com/articles/s44159-022-00089-1)); no self-serve platform reports this | Report it honestly, even when unflattering — it is the ledger's integrity |
| **Cost per weekly-active learner** | All-in inference / WAL, weekly | No public comparable; our own README shows ~$0.09 for one full research run pre-optimization | Daily session ≤ low single-digit cents via Haiku-routing + caching + evergreen reuse (levers shipped: ADRs 0021/0022) |

### 6.2 What we refuse to optimize

App-opens without sessions; minutes-in-app; notification click-through;
enrollments. Each is a vanity metric that the §3.4 contract forbids
weaponizing. **[judgment]**, stated as policy.

### 6.3 The kill-signal

If, six months post-launch, mentor-led sessions show the Khanmigo
shape — available to all, used weekly by <15%, with learning outcomes
indistinguishable from self-serve content browsing — the thesis is
falsified and the honest moves are narrowing to the personas that
*do* engage (likely Chen/Aisha, where the research side already
pulls) or stopping. Writing this down now is what makes it decidable
later.

---

## 7. What this document deliberately does not decide

- The mentor's internals — intake design, memory schema, planning
  horizon, prompt architecture: `01-LEARNING-AGENT.md`.
- Content strategy — course structure, curation standards, video
  licensing posture, synthesis-vs-evergreen boundaries:
  `02-CONTENT.md`.
- Architecture and sequencing — identity integration, storage,
  costs, phased delivery and gates: `03-ARCHITECTURE-ROADMAP.md`.
- Everything in §8, which belongs to the owner.

---

## 8. Open product questions for the owner

Q1–Q4 are blocking; the sibling documents cannot finalize without
them.

1. **Audience focus.** Which persona is the wedge? This document's
   ladder (§4.2) implies launching where trust is cheapest to earn —
   Aisha/Chen (paper-adjacent, served by existing machinery) — and
   growing toward Priya/Marcus/Sam. The alternative (beginner-first,
   biggest market, weakest fit to our unique machinery) is defensible
   and changes nearly every priority. **Blocking.**
2. **The free/paid boundary.** "Free courses" is promised; inference
   is not free. Where does the line sit — free evergreen content +
   metered mentor sessions? Free daily check-in + paid sprints and
   guided reads? A hard monthly inference allowance per learner? The
   answer sets the cost model and the F4-style global spend cap that
   must precede any launch. **Blocking.**
3. **MT-01 sequencing.** The platform requires per-user identity;
   MT-01 is PROPOSED with C1 (edge OIDC → per-user principals)
   recommended and a spend-cap prerequisite. Does the learning
   platform decision *approve* MT-01's direction now, and does
   identity work precede or run alongside learning-surface work?
   **Blocking.**
4. **Positioning and name.** Does this remain `arxiv-research-agent`
   with a learning surface, or become a named product of which
   research is one surface? Affects repo boundaries, branding, and
   whether the public repo stays the product's home. **Blocking.**
5. **Content stance on third-party video.** Curating freely available
   video (embeds, links) is cheap and legally light; anything more
   (mirroring, clipping, paid licensing) is a different business.
   How far may `02-CONTENT.md` go?
6. **Notification permission.** Daily check-ins imply email or push.
   How proactive may the mentor be, on which channels, and is the
   §3.4 respectful-retention contract adopted as stated policy?
7. **Credentialing.** Certificates: explicitly none (the ledger is
   the record), or a lightweight verifiable completion artifact?
   §4.2 ranks credentials below the line; confirm or overrule.
8. **Community scope for v1.** Forums/cohorts/study groups are
   deliberately absent from §5. In or out for the first year?
9. **The efficacy claim we're willing to make.** §3.8 caps honest
   marketing at ~0.3–0.5 SD-style claims and §6.1 commits to
   reporting retention-of-learning even when unflattering. Is that
   level of public honesty about outcomes accepted as strategy?
10. **Spend ceiling per learner.** Independent of pricing: what is
    the per-learner monthly inference ceiling the mentor must plan
    within (the learning-side analog of `max_cost_usd`), and what
    does the learner see when they reach it? (Per brief §P2, the
    answer must be visible *before* the session that would hit it.)

---

## 9. Source index

Repo grounding: [`README.md`](../../README.md),
[`docs/architecture.md`](../../docs/architecture.md),
[`docs/revamp/03-DESIGN-BRIEF.md`](../../docs/revamp/03-DESIGN-BRIEF.md),
[`docs/proposals/multi-tenancy.md`](../../docs/proposals/multi-tenancy.md),
[`planning/02-feature-ideas.md`](../02-feature-ideas.md),
[`planning/05-agentic-upgrade-plan.md`](../05-agentic-upgrade-plan.md).

External sources (all checked 2026-08-29):

- Reich & Ruipérez-Valiente, *The MOOC Pivot*, Science 2019 —
  [science.org](https://www.science.org/doi/10.1126/science.aav7958);
  [Inside Higher Ed](https://www.insidehighered.com/digital-learning/article/2019/01/16/study-offers-data-show-moocs-didnt-achieve-their-goals)
- Coursera Q2 2025 earnings —
  [marketbeat.com](https://www.marketbeat.com/earnings/reports/2025-7-24-coursera-inc-stock)
- fast.ai pedagogy —
  [Jeremy Howard on the whole-game approach](https://x.com/jeremyphoward/status/1296884279784255488);
  [top-down advocacy](https://bhatta.io/2018/10/20/why-i-advocate-fast-ai-top-down-approach/)
- Brilliant reviews —
  [SkillScouter](https://skillscouter.com/brilliant-review-math-science-coding/);
  [Brighterly](https://brighterly.com/blog/is-brilliant-org-worth-it/)
- Duolingo mechanics and criticism —
  [Trophy case study](https://trophy.so/blog/duolingo-gamification-case-study);
  [StriveCloud](https://www.strivecloud.io/blog/gamification-examples-boost-user-retention-duolingo);
  [Shauchenka teardown](https://www.uladshauchenka.com/p/duolingo-case-study-the-gamification)
- Khanmigo two-year RCT and usage —
  [trial summary](https://www.winssolutions.org/khanmigo-ai-tutoring-two-year-trial/);
  [Khan Academy blog](https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/)
- Papers with Code shutdown (2025-07-25) —
  [HyperAI](https://hyper.ai/en/news/42900);
  [Coursera explainer](https://www.coursera.org/articles/papers-with-code);
  [GitHub issue #116](https://github.com/paperswithcode/paperswithcode-data/issues/116)
- Elicit capabilities and caveats —
  [Manusights review](https://manusights.com/blog/is-elicit-worth-it);
  [PapersFlow survey](https://papersflow.ai/blog/best-elicit-alternatives-2026)
- Tutoring effect sizes —
  [Education Next](https://www.educationnext.org/two-sigma-tutoring-separating-science-fiction-from-science-fact/);
  [Nintil systematic review](https://nintil.com/bloom-sigma/)
- Spaced retrieval —
  [Nature Reviews Psychology 2022](https://www.nature.com/articles/s44159-022-00089-1)
