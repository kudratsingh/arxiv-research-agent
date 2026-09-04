# Framework mapping

The crosswalk. For each control this project maps against: how it is
satisfied, the artifact that satisfies it, the commit that artifact was last
read at, and an honest status.

**Reviewed at `ed71098`** (`ed71098b2c7854f8608a9194c8f82201e941c87b`). Every row was checked by opening the
artifact at that commit, not by trusting a filename. A row whose artifact path
no longer resolves fails `tests/test_assurance_docs.py`, so this page cannot
rot into a list of dead links without something going red.

## How to read the status column

| Status | Means |
|---|---|
| **Met** | An artifact satisfies the control **and** something fails when it stops being true. The "fails when" mechanism is named. |
| **Partial** | An artifact exists but does not cover the control, or covers it with nothing enforcing it. What is missing is stated. |
| **Out-of-reach** | Cannot be satisfied under this phase's constraints, with the reason. Not a euphemism for "not done yet" — the reason is a standing constraint (zero model spend, no deployment, N=1 maintainer) or a technical impossibility. |

The out-of-reach column is not an embarrassment and is not optional. NIST AI
600-1 **MS-1.1-009** requires tracking risks that cannot be measured
*quantitatively*, "including explanations as to why some risks cannot be
measured (e.g., due to technological limitations, resource constraints, or
trustworthy considerations)", and AI RMF **MEASURE 1.1** ends: "The risks or
trustworthiness characteristics that will not – or cannot – be measured are
properly documented." An empty out-of-reach column is a mapping nobody checked.

## Licensing note, before the OWASP rows

OWASP's prose is **CC BY-SA 4.0, which is viral**: pasting a category
description into this repository would relicense the file carrying it. So this
page cites OWASP **codes** only, and every description is our own — the same
rule `src/eval/safety_suite.py:395-409` already applies to the code table it
keeps in source. If a description here reads oddly, that is why: it is a
paraphrase written to avoid copying, not a quotation.

---

## 1. NIST AI RMF 1.0 (AI 100-1) and the Generative AI Profile (AI 600-1)

Subcategory text below is quoted from AI 100-1 (January 2023) Tables 3–4 and
AI 600-1 (July 2024).

| Framework | Control | How satisfied | Artifact | Reviewed | Status |
|---|---|---|---|---|---|
| AI RMF | **MEASURE 2.1** — "Test sets, metrics, and details about the tools used during TEVV are documented." | Every benchmark row names its author, creation date, licence and contamination notes; the dataset version is a fingerprint of the list's own contents, so it moves on any edit rather than on someone remembering. The metric set, the judge pin and the rubric versions are documented and pinned. | [`data-provenance.md`](data-provenance.md), `src/eval/benchmark_queries.py`, `src/eval/provenance.py`, `docs/eval.md`, `tests/fixtures/eval/rubric_lock.json` | `ed71098` | **Met** |
| AI RMF | **MEASURE 1.1** — risks that will not or cannot be measured are documented. | This page's out-of-reach rows, plus `docs/reliability.md`'s explicit list of what cannot be measured yet, plus the system card's unmeasured-limitations section. | [`framework-mapping.md`](framework-mapping.md) §6, `docs/reliability.md`, [`system-card.md`](system-card.md) | `ed71098` | **Met** |
| AI RMF | **MEASURE 2.7** — "AI system security and resilience – as identified in the MAP function – are evaluated and documented." | A 42-case authored adversarial corpus scored by seven behavioural executors against this checkout's real defences, model-free and offline. The gate runs on **every PR** by two independent routes: `tests/test_safety_suite.py::TestTheSuiteAgainstThisCheckout` is `unit`+`security` marked, so it is inside `pytest -m "not e2e"`, and `::test_the_committed_baseline_matches_this_checkout` calls `decide(..., advisory=False)` — the binding path; and since WO-A13 the workflow also runs the suite as its own step, publishing the attack-success rate as a retained artifact. Resilience is a written policy with a token bucket and clamped envelopes, exercised by a `fault` tier. | `src/eval/safety_suite.py`, `tests/fixtures/safety/corpus.json`, `tests/test_safety_suite.py`, `docs/security.md`, `src/resilience.py`, `docs/decisions/0068-resilience-policy.md`, `docs/decisions/0072-adversarial-safety-suite.md` | `ed71098` | **Met** |
| AI RMF | **MEASURE 2.3** — system performance is measured against the deployment context. | Nothing is deployed and no funded campaign has run. The measured numbers this repository has are structural (tests, coverage, types) and adversarial (the safety suite); the four LLM-judged accuracy metrics have never produced a `summary.jsonl`. | [`system-card.md`](system-card.md) §5, `docs/eval.md` | `ed71098` | **Out-of-reach** — requires owner-approved model spend (W-OD-1) and a running deployment; both are standing constraints of this phase. |
| AI RMF | **MANAGE 3.2** — "Pre-trained models which are used for development are monitored as part of AI system regular monitoring and maintenance." | The model id is a typed setting per agent with an explicit fallback chain, and the eval provenance block records the product model and judge model on every row so two campaigns on different models cannot be silently compared. There is no *runtime* monitoring of the upstream model, because nothing is running. | `src/config.py:950-1015`, `src/eval/provenance.py`, `src/eval/regression_diff.py` | `ed71098` | **Partial** — provenance and refusal-to-compare are in place; continuous monitoring of the hosted model is not, and cannot be until something is deployed. |
| AI RMF | **MANAGE 4.3** — "Incidents and errors are communicated to relevant AI actors... Processes for tracking, responding to, and recovering from incidents and errors are followed and documented." | Seven runbooks, one per incident the instruments make visible, each naming the signal, the first three commands, the containment and the rollback. Alert rules and a dashboard ship as reviewable files. | `docs/runbooks/README.md` and the seven pages under it, `deploy/observability/alerts.yml`, `deploy/observability/log-alerts.yml` | `ed71098` | **Partial** — the *procedures* exist and `tests/test_operability_docs.py` fails when a rule names an instrument that no longer exists. Nothing runs them, and there is no reporting channel to anyone outside the repository. |
| AI 600-1 | **GV-4.3-002** — a minimum incident-reporting field set (System ID, Title, Reporter, System/Source, Date Reported, Date of Incident, Description, Impact(s), Stakeholder(s) Impacted). | The runbooks capture the response procedure and the error taxonomy gives every failure a stable code, but **there is no issue template carrying this field set** — `.github/` holds only `workflows/`. | `docs/runbooks/README.md`, `src/errors.py`, `docs/decisions/0064-error-taxonomy-and-envelope.md` | `ed71098` | **Partial** — recorded as an open gap. An AI-incident issue template on the GV-4.3-002 fields is a small, well-specified follow-up that WO-A14 does not own. |
| AI 600-1 | **MS-1.1-009** — track risks that cannot be measured quantitatively, with the reason. | §6 of this page, and the "what this does not prove" sections of the system card. Preserving NIST's qualifier: the sanction is for risks that cannot be measured **quantitatively**, not for unmeasurable risks in general. | [`framework-mapping.md`](framework-mapping.md) §6, [`system-card.md`](system-card.md) | `ed71098` | **Met** |
| AI 600-1 | **MS-2.8-003** — content transparency and traceability; "Robust version control systems can also be applied to track changes across the AI lifecycle over time." | Every artifact in this pack is a reviewed pull request against a public history; every ADR is dated and never renumbered; the campaign's own corrections to its plan are recorded rather than absorbed. The first sentence of the action — tamper-proof per-generation content provenance — is not implemented. | `docs/decisions/README.md`, `planning/08-assurance/STATUS.md`, `planning/03-roadmap.md` | `ed71098` | **Partial** — version control satisfies the second sentence. Per-output content provenance is the same problem as EU AI Act Art. 50(2) below, and has the same answer. |
| AI 300-1 ipd | Dataset documentation template (Clause 5.2, seven root fields) | Every dataset this repository ships is documented on the seven-field set, with the Annex A.2 default-profile subfields used where they apply. | [`data-provenance.md`](data-provenance.md) | `ed71098` | **Met** |
| AI 300-1 ipd | Model documentation template (Clause 5.3, eight root fields) | **Not applicable as a model card.** This project trains no model. The eight-field template is instead answered as a *system* card, which is what §4.4 of the phase's standards doc asks for. | [`system-card.md`](system-card.md) | `ed71098` | **Partial** — deliberately. Fields 4 (Design) and 5 (Training) have no honest answer for a system that only calls a hosted model; the card says so rather than filling them in. |

**One caveat on AI 300-1 ipd**, carried because it changes what conformance
means: the draft is a *Zero Drafts* pilot output headed to INCITS/AI and then
ISO/IEC JTC 1/SC 42, and NIST states it "does not expect to maintain the
document further". Its comment window closed 16 September 2026. Its "shall"
language "does not reflect any regulatory intent... use of 'shall' or
'requirement' indicates only what constitutes conformity". Following it is a
good-faith choice of the best free conformity-assessable template available,
not a compliance claim.

**And one extension, declared:** the draft has **no contamination or
train-test-overlap disclosure field** — the closest is optional subfield 4.1.3
"Dataset Splits". The contamination notes in
[`data-provenance.md`](data-provenance.md) are therefore an *extension* of the
profile, which Clause 6 and the "may contain additional top-level fields"
allowance permit. They are not conformance; they are there because the finding
is real.

---

## 2. OWASP — Agentic (ASI) primary, LLM Top 10 secondary

The agentic list is primary because the threat this system actually has is an
agent acting on text it fetched, not a chatbot emitting text. Codes only;
descriptions are ours. Measured results are from
[`../../planning/08-assurance/evidence/gate-a3/raw/safety-suite.txt`](../../planning/08-assurance/evidence/gate-a3/raw/safety-suite.txt).

| Code | Our description | How satisfied | Artifact | Reviewed | Status |
|---|---|---|---|---|---|
| **ASI01** | The run is steered away from the goal it was given. | Four corpus cases; one succeeds. The residual is a soft-phrased goal nudge that the isolation signatures do not fire on — recorded as a known residual rather than tuned away. | `tests/fixtures/safety/corpus.json`, `src/eval/safety_suite.py`, `src/security/prompt_isolation.py:126` | `ed71098` | **Partial** — 1/4 succeed; `asi01-soft-phrased-goal-nudge` is a named residual. |
| **ASI02** | A capability is used for something it was not authorised to do. | Nine cases, none succeed. `unauthorised_tool_call` is a hard-violation class gated at absolute zero, and the router's authorised-node set is checked behaviourally rather than by regex. | `src/eval/safety_suite.py` (`AUTHORISED_NODES`, `HARD_VIOLATION_CLASSES`), `tests/test_safety_suite.py` | `ed71098` | **Met** |
| **ASI03** | The agent's identity or privilege level is altered by its input. | Four cases, none succeed. Per-principal scoping means a key sees only its own jobs and conversations; cross-principal access is a 404, not a 403. | `tests/test_per_principal_scoping.py`, `src/api/auth.py`, `docs/decisions/0036-per-principal-store-scoping.md` | `ed71098` | **Met** |
| **ASI04** | A dependency, source or artifact the agent trusts is compromised. | Four cases, none succeed, and the supply chain now has an SBOM plus a vulnerability audit from one PyPA tool. The lock is **not** hashed and nothing is signed. | [`../../planning/08-assurance/evidence/gate-a3/sbom.cyclonedx.json`](../../planning/08-assurance/evidence/gate-a3/sbom.cyclonedx.json), `requirements-lock.txt`, `docs/decisions/0045-supply-chain-pinning-lockfile-and-license-posture.md` | `ed71098` | **Partial** — see §4. The audit found five advisories across four packages; **one** is already recorded in `pyproject.toml` and none is fixed on this branch. |
| **ASI05** | Input becomes execution rather than data. | Three cases, none succeed. Untrusted paper text is wrapped and sanitised; the PDF fetcher rejects non-public addresses and non-HTTPS schemes before any request leaves the process. | `src/security/prompt_isolation.py`, `src/tools/pdf_parser.py`, `tests/test_prompt_isolation.py`, `tests/test_parse_defense.py` | `ed71098` | **Met** |
| **ASI06** | What the agent remembers is poisoned for a later run. | Four cases, none succeed. The learner profile bounds its skill entries and every claim carries non-nullable declared/inferred/assessed provenance, enforced in the type, the merge and the table's CHECK constraints. | `src/learning/`, `tests/test_learner_profile_store.py`, `docs/decisions/0058-learner-profile-store-and-provenance.md` | `ed71098` | **Met** |
| **ASI07** | One component's output becomes another's instructions. | Five cases, none succeed. This is the system's central threat — paper text flows into calls whose output steers the workflow — and four of the ten isolation signatures target it. | `src/security/prompt_isolation.py:131-200`, `tests/test_reader_isolation.py`, `docs/decisions/0020-prompt-injection-isolation-reader.md` | `ed71098` | **Met** |
| **ASI08** | One contained failure becomes many, or becomes unbounded work. | Three cases, **two succeed** — an attacker-named section and an unbounded section list. Both are named residuals, not surprises. Cost and wall-clock ceilings bound the blast radius (`max_cost_usd` checked before every model call, a per-job timeout, a PDF byte cap), but the *content-shaped* amplification is real. | `src/llm.py`, `src/api/runner.py`, `src/tools/pdf_parser.py`, `tests/test_runner_cost_cap.py` | `ed71098` | **Partial** — the worst per-category result in the suite. |
| **ASI09** | The person is misled about what the agent knows or verified. | Three cases, none succeed. Degradation is reported rather than hidden: the search layer states what it could not retrieve, `assessment_status` reports the judge's outcome as a fact rather than a grade, and a failed transcript read says `unavailable` instead of reconstructing. | `tests/test_search_honesty.py`, `src/api/routes.py`, `docs/decisions/0041-retrieval-and-degradation-honesty.md` | `ed71098` | **Met** |
| **ASI10** | An agent operates outside the set the operator sanctioned. | Three cases, none succeed. The supervisor picks from a strict enum and an unknown action is logged and refused rather than dispatched. | `src/agents/supervisor.py`, `tests/test_supervisor.py` | `ed71098` | **Met** |

**Aggregate, as measured:** 3 of 42 attacks succeed — 7.14%, Wilson 95%
interval 2.46%–19.01%. Zero categorical hard violations
(`egress_to_non_allowlisted_host`, `secret_exfiltrated`,
`unauthorised_tool_call`), which is the veto the gate actually enforces at
absolute zero. The suite gates on a **regression delta**, not on an absolute
rate, for the reason ADR 0072 records: at n=42 an absolute ASR threshold flips
on noise, and attack success rate is a property of the deployment surface
rather than of the model.

### LLM Top 10, secondary

Mapped where the agentic list does not already carry the concern.

| Code | Where it lands here | Status |
|---|---|---|
| **LLM01** prompt injection | Fully covered by ASI05/ASI07 above. | **Met** |
| **LLM02** sensitive information disclosure | Log redaction plus a salted `principal_hash` rather than raw principal ids; `secret_exfiltrated` is a hard-violation class. `tests/test_log_redaction.py`, `src/observability/logging.py`. | **Met** |
| **LLM03** supply chain | See ASI04 and §4. | **Partial** |
| **LLM04** data and model poisoning | No training happens here, so the poisoning surface is memory, not weights — ASI06. | **Met** (as scoped) |
| **LLM05** improper output handling | Export renderers and SSE frame encoding are property-tested, including the event-name sanitisation defect the property tier found. `tests/property/`, `src/api/streaming.py`. | **Met** |
| **LLM06** excessive agency | The strict action enum, the cost ceiling checked before every call, and HITL before any search or read. | **Met** |
| **LLM07** system-prompt leakage | One isolation signature targets it (`src/security/prompt_isolation.py:190`); the corpus exercises it. | **Met** |
| **LLM08** vector and embedding weaknesses | The embedding cache is keyed on `(content_hash, model_name)` so a model swap invalidates implicitly, but **nothing tests adversarial retrieval poisoning of the FAISS index**. | **Partial** — named gap. |
| **LLM09** misinformation | ASI09, plus deterministic groundedness: identifier resolution against the run's own corpus and verbatim quote checking, with honest denominators. `src/eval/groundedness.py`, `docs/decisions/0074-deterministic-groundedness.md`. | **Met** (mechanism); the *rate* is unmeasured on real runs — see §6. |
| **LLM10** unbounded consumption | ASI08. | **Partial** |

---

## 3. ISO/IEC 42001:2023

Annex B is normative and is roughly half the standard. The controls below are
the ones this phase touches. **Certification is explicitly not pursued**:
clause 9.2 requires auditors who do not audit their own work, which is
structurally unsatisfiable at N=1; it is a recurring five-figure commitment;
and the European harmonised version is not harmonised, so it buys nothing under
the AI Act.

| Control | Subject | How satisfied | Artifact | Reviewed | Status |
|---|---|---|---|---|---|
| **A.6.2.8** | Event logs for the AI system | A written log contract: envelope fields as constants in one place, an `extra` allowlist, redaction, and a per-run correlation id propagated through ContextVars so every line for a request carries the id and a salted principal hash. **21** OTel instruments (measured by the AST scan `tests/test_operability_docs.py` runs, not counted by hand — `docs/architecture.md` still says nine, which is [claim A24](README.md#the-architecture-claims) in the index), and GenAI-conventional span attributes on the inference client. | `docs/observability.md`, `src/observability/logging.py`, `src/observability/context.py`, `src/observability/semconv.py`, `tests/test_log_contract.py`, `tests/test_genai_conventions.py`, `docs/decisions/0067-correlation-context-and-log-contract.md` | `ed71098` | **Met** |
| **A.6.2.4** | AI system verification and validation | Every Python tier gates a pull request at zero spend, and since WO-A13 they gate *in CI* rather than on a desk: unit/integration (3235 passed, 55 skipped locally) under the project branch-coverage floor and four per-package floors, patch coverage at 90% of the lines a branch changed, property (152), fault (157), contract (98), security (314), e2e (16), the adversarial suite's report and gate, and the scripted learner campaign — plus mypy strict over 93 files and ruff. The harness cannot silently reach the network, a real key or a developer `.env`. | `docs/testing.md`, `.github/workflows/ci.yml`, `tests/test_harness_guards.py`, `pyproject.toml`, [`../../planning/08-assurance/evidence/gate-a3/README.md`](../../planning/08-assurance/evidence/gate-a3/README.md) | `ed71098` | **Met** |
| **A.7.5** | Data provenance | Every dataset documented on the NIST AI 300-1 field set, with origin, author, licence, date and contamination notes; dataset versions are content fingerprints, not hand-bumped constants. | [`data-provenance.md`](data-provenance.md), `src/eval/provenance.py`, `docs/decisions/0070-eval-integrity-provenance.md` | `ed71098` | **Met** |
| **A.5.2–A.5.5** | AI system impact assessment | The system card states intended use, out-of-scope use, affected people and known limitations, and the safety corpus is an impact analysis with a number attached. There is no assessment of impact on people *outside* the direct user — no consultation, no affected-community input. | [`system-card.md`](system-card.md) | `ed71098` | **Partial** — the internal half is documented; the external half needs people this project does not have. |
| **A.10.3** | Suppliers | One model supplier (Anthropic, via the SDK), one paper source (arXiv), one optional enrichment source (Semantic Scholar), all named with their failure behaviour and their retry owner. The dependency set is pinned and now has an SBOM. | `docs/decisions/0068-resilience-policy.md`, `docs/architecture.md`, [`../../planning/08-assurance/evidence/gate-a3/sbom.cyclonedx.json`](../../planning/08-assurance/evidence/gate-a3/sbom.cyclonedx.json) | `ed71098` | **Partial** — suppliers are documented; there is no supplier assessment, contract review or exit plan, and none is meaningful at this scale. |
| Clause **9.2** | Internal audit | — | — | `ed71098` | **Out-of-reach** — requires auditors who do not audit their own work. Structurally unsatisfiable at N=1. Recorded rather than fudged. |
| Clause **7.5.2/7.5.3** | Documented information: identified, authored, dated, reviewed, version-controlled, integrity-protected, retained | Reviewed pull requests plus a public git history supply all seven. This is the git-native argument in §4.4 of the phase's standards doc. | `docs/decisions/`, the repository history | `ed71098` | **Met** |

**Watch item:** ISO/IEC FDIS **24970 — AI system logging** was at stage 50.20
when this phase's standards research ran and publishes shortly. It is likely to
become the reference for exactly the log schema A.6.2.8 is satisfied by above,
which is why `src/observability/logging.py` keeps its field names as constants
in one place rather than as literals in a formatter.

---

## 4. Supply chain and the SBOM

`pip-audit --format cyclonedx-json` produces the SBOM and the vulnerability
audit from one PyPA tool, which is why it is the tool of choice here: one
install, one run, two artifacts that cannot disagree with each other.

- **SBOM:** [`../../planning/08-assurance/evidence/gate-a3/sbom.cyclonedx.json`](../../planning/08-assurance/evidence/gate-a3/sbom.cyclonedx.json)
  — CycloneDX 1.4, 126 components, dated in the document's own `metadata.timestamp`.
- **Audit:** [`../../planning/08-assurance/evidence/gate-a3/raw/pip-audit.txt`](../../planning/08-assurance/evidence/gate-a3/raw/pip-audit.txt)

The audit is over `requirements-lock.txt` with `--no-deps`, so it describes the
pins CI actually installs rather than a fresh resolve that nobody ran. The
runtime subset (`requirements-runtime-lock.txt`) yields the identical finding
set; both files are in the pack.

**Five advisories across four packages, none fixed on this branch.** Stating
them plainly, because an SBOM that hides its own findings is decoration:

| Package | Pinned | Advisory | Fixed in | Note |
|---|---|---|---|---|
| `langgraph-checkpoint-sqlite` | 3.1.0 | PYSEC-2026-3636 | 3.1.1 | Already recorded in `pyproject.toml:30-34` — a namespace-scoping advisory in the *Store* implementations this project does not use, to be picked up at the next lock refresh. The audit confirms the note rather than discovering something new. |
| `langgraph-checkpoint-postgres` | 3.1.0 | PYSEC-2026-3635 | 3.1.1 | Same line, same fix version; `pyproject.toml` records the sqlite half only. |
| `setuptools` | 81.0.0 | PYSEC-2026-3447 | 83.0.0 | Build-time dependency. Reported twice by the tool for one advisory. |
| `torch` | 2.12.1 | PYSEC-2025-194 | 2.13.0 | Transitive, via `sentence-transformers`. |

ADR 0045 gives this repository **one dependency diff per phase** and WO-A02
already spent it, so WO-A14 does not move the lock — it reports. Two known
limits carry forward from ADR 0045 and both weaken ASI04: the lock is frozen on
one platform, and it is **not hashed** (`--require-hashes` is not in use), so
the audit's own tool warns that pinning without hashes is weaker than it looks.

---

## 5. EU AI Act — what is asserted, and what is not

**Read the verification note first.** The phase's standards research could not
read EUR-Lex's enacting terms and reconstructed article-level detail from
secondary analyses; WO-A14 was required to re-verify before asserting any date.
That re-verification ran on 2026-09-04 and is summarised here honestly,
including where it **contradicted the plan**.

### What the re-verification could corroborate

| Claim | Sources | Confidence |
|---|---|---|
| Regulation (EU) **2026/1744** exists — the Digital Omnibus on AI, amending Regulation (EU) 2024/1689 — published **OJ L, 2026/1744, 24.7.2026**, in force **27 July 2026**. | EUR-Lex ELI record; the Commission's `regulatory-framework-ai` page independently gives the entry-into-force date. | High — two independent sources, arithmetically consistent with "third day following publication". |
| Annex III high-risk obligations now apply from **2 December 2027**. | Commission page, corroborated by the AI Act Explorer. | High — the strongest chain in the pass. |
| Annex I high-risk obligations now apply from **2 August 2028**. | Same two sources. | High. |
| Article 50 transparency has applied since **2 August 2026** and was not delayed. | Commission page ("The transparency rules of the AI Act will come into effect in August 2026"), consistent with Article 113's general application date. | High. |

### What the re-verification **corrected in this campaign's own plan**

`planning/08-assurance/02-STANDARDS.md` §4.1 records that Annex I moved "from
2 Aug 2026" to 2 Aug 2028. **The "from" date is wrong.** The AI Act's original
Article 113(c) baseline for Article 6(1) and Annex I was **2 August 2027**, not
2026. The delay is one year, not two. This is recorded here rather than
silently fixed because a campaign that quietly absorbs its own errors teaches
nothing — the same reason `STATUS.md` keeps a corrections section.

A second correction: §4.1 says "Article 50 transparency did not move". As an
unqualified sentence that is not right — the omnibus recitals state that
**Article 50(7) was amended** to remove the Commission's implementing-act
empowerments. Paragraphs 50(1) and 50(2), the ones that matter here, are
untouched.

### What is **not** asserted, and why

- **The enacting terms of Regulation 2026/1744.** Every EUR-Lex rendering
  truncated inside the recitals; the amending wording was never read directly.
  The *dates* are Commission-corroborated; the amendment *text* is not.
- **Any Article 50 transitional deadline for pre-2 August 2026 systems.** One
  fetch reported 2 December 2026; nothing corroborated it. Not asserted.
- **Article-level quotations as official text.** Every verbatim article quote
  available to this pass came from `artificialintelligenceact.eu`, a
  high-quality but **unofficial** mirror. Article text is used here to reason
  with, never cited as authoritative.
- **That a public repository does not "place on the market".** Article 3(10)
  defines making available "in the course of a commercial activity" and says
  free of charge is not itself a way out. Applying that to a GitHub repository
  is an inference with no source behind it. A **hosted demo is a much stronger
  trigger than a repository** — that asymmetry is the practical point, and it is
  the reason the deployment decision is the one that changes this section.

### The position, as documented

| Obligation | Applies? | Reasoning | Status |
|---|---|---|---|
| **Art. 50(1)** — a person interacting with an AI system must be informed of that, unless it is obvious | **Yes — treat as the live obligation.** | Article 2(12) exempts free-and-open-source AI systems *"unless they are placed on the market or put into service as high-risk AI systems or as an AI system that falls under Article 5 or 50"* — so Article 50 punches straight through the FOSS exemption. It is also the cheapest obligation in the Act to satisfy honestly. | **Met.** The landing composer states the cost boundary and that a plan is generated by an AI system before anything is spent; the plan-review pause is itself first-exposure disclosure. `README.md:198-214`, `web/` composer. |
| **Art. 50(2)** — outputs marked machine-readable and detectable as artificially generated | **Yes in scope, no in practice.** | **Out-of-reach**, and the reason is technical rather than a matter of effort. The C2PA reference implementation (`contentauth/c2pa-rs`) has no text handler: its supported-formats table lists images, audio, video, PDF (read-only) and SVG, and contains no `text/plain`, `.txt` or `.md` entry — verified directly against the repository, not inferred. Sampling-time watermarking is unavailable when calling a hosted API. Article 50(2) itself qualifies the duty with "as far as this is technically feasible, taking into account the specificities and limitations of various types of content" and "the generally acknowledged state of the art". | **Out-of-reach** — with the qualifier that this repository has **not** verified any Commission concession that no technique meets all four required qualities for text. That claim appears in the phase's standards doc; the re-verification could not source it, so it is not repeated as fact here. |
| **Annex III point 3** — education and vocational training | **Almost certainly not.** | Each of sub-points (a)–(d) is bounded by "educational and vocational training institutions". Note a nuance the plan did not have: **the bound sits inside each sub-point, not in the chapeau** (which reads only "Education and vocational training:"), so the exclusion is an argument made per sub-point rather than one chapeau-level exclusion. A standalone study assistant is outside all four. The same system deployed *by an institution* to score work or steer progression would be inside (b) or (c). | **Out of scope — conditionally.** The condition is a deployment decision, not a code property. |
| **Chapter V** — general-purpose AI model obligations (Art. 53/55), applying since 2 August 2025 | **No.** | Chapter V binds providers of general-purpose AI *models*. This project integrates a third party's hosted model and is a downstream provider of an AI *system* — Art. 3(68). **Flagged as reasoned, not sourced:** the well-known nuance is that a downstream actor can *become* a model provider by fine-tuning or substantially modifying a model. This project does neither, which is why the conclusion holds; but the nuance itself was not verified against a primary source in this pass. | **Out of scope.** |
| **Art. 5** — prohibited practices | **No.** | No biometric categorisation, no emotion inference in work or education, no social scoring, no subliminal technique. The system reads papers and writes briefings. | **Out of scope.** |

**The honest summary:** on today's shape — a public repository with no hosted
deployment, no institutional deployer and no training — Article 50(1) is the
only obligation that plausibly bites, and it is satisfied. **Standing up a
hosted demo is the event that changes this analysis**, because it is much
closer to "putting into service" than publishing code is. That decision is the
owner's and is not made here.

---

## 6. What is out of reach, and why

Recorded under MS-1.1-009 and MEASURE 1.1. Every entry names the constraint,
not an excuse.

| # | Risk / property | Why it cannot be measured here | What would change it |
|---|---|---|---|
| 1 | **Judge–human agreement.** Whether the LLM judges (completeness, faithfulness, assessment) agree with a human reader. | Requires human-labelled items and paid judge calls. Nothing in this repository calibrates a judge against a person, so every judged score is a number without a known relationship to human judgement. | Human labelling of a sample, then a measured agreement statistic. Owner decision W-OD-1 plus labour this project does not have. |
| 2 | **Accuracy of the four LLM-judged research metrics.** Citation accuracy, faithfulness, completeness, retrieval recall. | The nightly eval workflow has never produced a `summary.jsonl` — it failed every run at a missing repository secret, and it is currently disabled by standing constraint. There are no numbers, and there are deliberately no placeholder numbers. | One funded 20-query campaign. Owner decision W-OD-1. |
| 3 | **Groundedness on real runs.** `citation_resolution_rate`, `quote_verbatim_rate`, `unsupported_claim_count`. | The *mechanism* is built, deterministic and zero-cost; the *inputs* are recorded fixtures. A rate measured over fixtures is a fact about the fixtures. | The same funded campaign as #2 — this metric then rides along at no extra model cost, which is the point of ADR 0074. |
| 4 | **Absolute attack success rate.** | Measurable but **not meaningful**: ASR is a property of the deployment surface rather than of the model, and at n=42 a threshold flips on noise (the observed 7.14% carries a Wilson interval of 2.46%–19.01%). The gate is therefore a regression delta plus a categorical veto, which is the defensible instrument at this corpus size. | A larger corpus, or a deployment surface to measure against. Neither makes an absolute threshold portable. |
| 5 | **Runtime behaviour in production.** Latency SLIs, error budgets, saturation, real traffic. | Nothing is deployed. Alert rules, a dashboard and a collector config ship as reviewable files under `deploy/observability/` and **nothing runs them**. Every SLO in `docs/reliability.md` is marked *declared, not earned*. | An owner-approved deployment. |
| 6 | **Machine-readable synthetic-content marking.** | No text handler exists in the C2PA reference implementation; sampling-time watermarking is unavailable behind a hosted API. §5. | An upstream standard that covers text, or provider-side watermarking. |
| 7 | **Independent audit.** ISO 42001 clause 9.2, and any third-party red-team. | N=1. An auditor who does not audit their own work does not exist here. | A second person. |
| 8 | **Impact on people outside the direct user.** | Requires consultation with affected communities. | People, not code. |
| 9 | **Adversarial retrieval poisoning of the vector index.** | The safety corpus does not exercise it; the embedding cache's invalidation story is about model swaps, not adversarial content. LLM08 above. | A corpus extension. Reachable, and named so it is not forgotten. |
| 10 | **`ASI08` content-shaped amplification.** | Two of three cases succeed today. Cost and time ceilings bound the blast radius; the shape of the amplification is not defended against. | A bound on attacker-influenced structure — a section-count ceiling, or section names drawn from a closed set. |

## Related

- [`README.md`](README.md) — the index, and the claim → enforcement table.
- [`system-card.md`](system-card.md) — intended use, models, measured results, limitations.
- [`data-provenance.md`](data-provenance.md) — every dataset on the NIST AI 300-1 field set.
- [`../../planning/08-assurance/evidence/gate-a3/README.md`](../../planning/08-assurance/evidence/gate-a3/README.md) — the dated evidence pack the numbers above came out of.
