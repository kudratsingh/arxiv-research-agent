# Assurance

The index. Open this, and every claim this repository makes about reliability,
safety, accuracy and compliance leads to the artifact that enforces it — or to a
plain statement that nothing does.

**Reviewed at `ed71098`; claim rows revised by WO-B1, WO-C2 and WO-D2.**
Every path cited on this page and in
[`framework-mapping.md`](framework-mapping.md) resolves, and
`tests/test_assurance_docs.py` fails when one stops resolving. A crosswalk full
of dead links is worse than no crosswalk. The `file:line` column was recomputed
against the tree WO-B1 left behind, and recomputed again for WO-C2 and WO-D2:
correcting
a false sentence moves the line numbers of every claim below it, and a citation
that points at the wrong line is the same species of rot the rest of this page
is about.

## The pack

| Document | What it answers |
|---|---|
| [`system-card.md`](system-card.md) | What the system is for, what it must not be used for, which models it routes to, what has actually been measured, and what has not. A **system** card: this project trains no model. |
| [`data-provenance.md`](data-provenance.md) | Every dataset the repository ships, on the NIST AI 300-1 ipd seven-field template — origin, author, licence, date, and contamination notes. |
| [`framework-mapping.md`](framework-mapping.md) | The crosswalk: NIST AI RMF and the GenAI Profile, OWASP Agentic (ASI) primary with the LLM Top 10 secondary, ISO/IEC 42001, the EU AI Act, and the SBOM. Met / Partial / **Out-of-reach**, with the out-of-reach column filled in. |
| [Claim → enforcement index](#claim--enforcement-index) | Below. Every claim in `README.md` and `docs/architecture.md`, and what goes red when it stops being true. |
| [`../../planning/08-assurance/evidence/gate-a3/README.md`](../../planning/08-assurance/evidence/gate-a3/README.md) | The dated Gate A3 evidence pack. Every number in this directory came out of a runner and is traceable to a file in `raw/`. |

## What a reviewer should read first

If you have five minutes and want to know whether to trust this system:

1. [`system-card.md`](system-card.md) §5.2 — **no accuracy metric has ever been
   measured on a real run.** That is the headline and nothing below it changes
   it.
2. [`system-card.md`](system-card.md) §5.3 — **judge–human calibration is
   unmeasured.** Every judged score has no known relationship to human
   judgement.
3. [The claim that was still false](#the-claim-that-was-still-false), below.
   Eleven claims were unenforced when this page was written and five of those
   were false; after WO-B1, WO-C2 and WO-D2 the count is zero unenforced and
   zero false — which is **not** a clean bill of health, and the paragraph
   under the status table says why: twenty-one claims are Partial, each with
   its gap named in its own row.
4. [`framework-mapping.md`](framework-mapping.md) §6 — the ten things that
   cannot be measured here, each with the constraint that makes it so.

---

## Claim → enforcement index

**70 claims** were extracted from `README.md` (45) and `docs/architecture.md`
(25). For each: what fails when it stops being true.

| Status | Count | Means |
|---|---|---|
| **Enforced** | 49 | A named test, gate or validator goes red. |
| **Partial** | 21 | Something goes red, but narrower than the claim. The gap is named. |
| **Not enforced** | 0 | Nothing goes red. |
| **False** | 0 | The claim is untrue on this tree. Also unenforced, by definition. |

The last two rows are the valuable part of this document. A claim nothing
enforces is a claim that will drift, and five already had when this page was
first written.

**Read the zero carefully.** It does not mean this repository is all-green;
it means every claim now has *something* behind it, and twenty-one of them
have less behind them than the sentence says. The gap did not disappear when
a row moved from "Not enforced" to "Partial" — it moved into that row's
right-hand column, where it is named. Three of the four rows WO-C2 moved
carry a residue that no test in this repository can reach: the nightly's
real state lives in GitHub's settings rather than the tree (R28), no
reflection over `Settings` can see a feature that shipped with no flag at
all (R15), and the screenshots (R14) — which WO-D2 turned into Playwright
snapshots — are compared by a gate that runs on macOS and skips in CI.

**Revised by WO-B1**, which added
[`tests/test_documented_claims.py`](../../tests/test_documented_claims.py).
Four of the five false claims were corrected and are now read back out of the
prose by a test; the fifth (**A25**) stayed false until WO-D2. Row by row: R22 False → Partial, R25 False → **Enforced**, A09 False →
**Enforced**, A24 False → **Enforced**, R16 Not enforced → Partial, R33 Not
enforced → Partial. Nothing was reclassified without a test to point at, and
no claim was weakened to make a test pass — where a claim could not be
mechanised the claim stayed and the gap is below.

**Revised again by WO-C2**, which took the four remaining unenforced rows:
R11 Not enforced → **Enforced**, R14 Not enforced → Partial, R15 Not enforced
→ Partial, R28 Not enforced → Partial. A25 stayed False, and WO-D2 closed it:
False → **Enforced**. One sentence was rewritten rather than
mechanised — R11's "byte-identical", which no artifact in this repository
could ever have supported — and the row says so where a reader will see it.

**Revised again by WO-D2**, which took the last false claim and the residue of
one Partial row: A25 False → **Enforced**, R14 Partial → Partial *with the
images bound*. It also corrected two stale `docs/demo.md` anchors and re-seeded
the Vitest count of record, and both of those are now held by a test rather
than fixed once.

**One correction to this page's own account of itself.** A25's row below said
its test was "already written". It was not. `TestTheNightlyEvalState` held
`README.md`, `docs/eval.md` and the two workflow files, and **no test in this
repository read `docs/architecture.md`'s nightly sentence at all** — which is
precisely why the claim could sit false through two work orders without going
red. A sentence no test reads is not waiting on an edit; it is unenforced, and
this page had recorded the opposite. WO-D2 wrote the missing test and made the
edit in the same commit.

### The claim that was still false

It was eleven claims that nothing enforced, then five, then one — and now
none. The eleven that left the list are recorded underneath, because *how* a
claim became enforceable is the part worth copying.

| Claim | What it says now | What goes red |
|---|---|---|
| **A25** — the nightly eval, in `docs/architecture.md` | "**designed to run nightly in CI** with regression diffing… **It does not run:** the nightly eval workflow is **disabled at the repository** (`disabled_manually`) and stays that way pending the owner's funding decision, so `eval-nightly.yml` keeps a `cron:` that GitHub ignores and says so beside it." The document that had been the odd one out now tells the same story as the other three, and links the long form in `docs/eval.md`. | `TestTheNightlyEvalState::test_the_architecture_doc_tells_the_same_story` — two assertions, because the sentence can rot in two directions: no unqualified "runs nightly in CI" anywhere in the document, and the disabled state stated rather than merely implied by the qualifier. Restoring origin/main's wording fails the first; deleting the disabled clause while keeping "designed to" fails the second. |

### The eleven that left the list, and what closed each

| Claim | What it says now | What goes red |
|---|---|---|
| **R33** — the routing saving | The saving is **modelled, not measured**, and the arithmetic is on the page: `src/observability/costs.py` prices Haiku 4.5 at exactly one third of Sonnet 4.6 per token, so routing a share *s* of a run's token spend cuts the total by `2/3 × s` — 50-60% at a 75-90% routed share. "Baseline quality preserved" is **gone**, with its absence explained rather than trimmed. No number was invented. | `TestTheModelledRoutingSaving` recomputes the band from the shipped price table and fails if the two move apart, and trips if the "modelled, not measured" qualifier is deleted. **Still Partial:** the 75-90% share is ADR 0021's argument from call volume, not a measurement, and no run in this repository has ever been priced under the routed mapping. |
| **R22** — the test counts | "**nine parallel jobs**", "**over 3,300 tests**", "**3,380 Vitest tests across 155 files**", followed by a paragraph saying which figure is a floor, which is an equality, and why. | `TestTheCiJobCount` counts `jobs:` in `ci.yml` and fails on any `needs:` edge; `TestThePythonSuiteCount` collects the whole suite in a subprocess and checks the floor *and* that the floor has not fallen more than 500 behind it; `TestTheVitestCounts` reads the last coverage re-seed note in `web/vitest.config.mts`. **Still Partial:** the Vitest figure is an agreement between two documents rather than a measurement — nothing in the Python tier counts the web suite, and nothing should. |
| **R25** — the `e2e` tier | The tier is **built and gates every pull request** — sixteen tests across four modules, run by `make test-e2e` in the `tests` job. What is missing is **recorded cassettes**, and the project-status row says that now instead of "the marker is registered and unused". | `TestTheE2eTier`: the test count as an equality against `pytest -m e2e`, the module count against the directory, a proof that the marker set and the directory are the same set (so the count is about a *tier*, not a folder), and the `make test-e2e` step in `ci.yml`. |
| **A09** — `run_job`'s kind branches | "**Five further branches on `job.kind`** live in `run_job` itself", each one named: the cost cap, the per-node cost log, progress-event persistence, the profile write, and breached-cap behaviour. | `TestTheJobKindBranches` walks `run_job`'s AST, counts comparisons against `job.kind`, and requires equality — the claim is that the set is closed, so a sixth branch is a failing test rather than a stale sentence. |
| **A24** — the instrument count | "**twenty-two** OTel instruments", with the families enumerated. | `TestTheInstrumentCount` compares the sentence against `tests/test_operability_docs.py`'s AST scan of `src/`. One scan, two readers: the claims file has no second implementation to be subtly wrong about. |
| **R16** — every decision has an ADR | Unchanged. The claim was always true; nothing read it. | `TestTheAdrIndex` requires the index and `docs/decisions/` to be the same set, and every ADR linked from `README.md` or `docs/architecture.md` to exist. **Still Partial:** "non-trivial" is a judgement and no test will hold it. |
| **R11** — the standalone defaults | The three backends, unchanged, plus what they buy: "a checkout with neither Redis nor Postgres runs the **Sprint 1 storage path** unchanged". **"So Sprint 1 behavior stays byte-identical" is gone**, and its absence is explained in the sentence rather than trimmed out of it: no Sprint 1 artifact is kept here to diff against and the outputs are model-generated, so byte-identity was not a claim any test could hold — or, for that matter, a claim that was true. | `TestTheStandaloneDefaults` reads the three backends out of the sentence and re-derives them from `Settings`' declared defaults (not from a live `Settings()`, whose answer an exported `JOB_STORE` would change), and `::test_none_of_the_three_needs_a_service` fails with the reason rather than with a diff. `tests/test_config.py::TestDefaults::test_standalone_storage_defaults` is the config surface's own copy of the same three values, which is where WO-B1's note said they belonged. |
| **R14** — the screenshots | The mechanism as before, and the part WO-C2 could only state is now done: **each of the five images is a Playwright snapshot**, captured by `web/e2e/readme.spec.ts` and regenerated with `npm run e2e:readme:update`. The README says so, and says the limit in the same breath — **the comparison runs on macOS only**. | `TestTheScreenshotMechanism`: `seed.sh` writes through `psql` and `redis-cli` and issues no `POST` and no `/research`, the stack is pinned to the sentinel the README names, every image the README renders exists, and — new — the set the README renders and the set the spec captures are the same set, so an image added by hand goes red on any platform. **Still Partial, for a different reason than before.** The pixels are compared by a browser gate that cannot carry a `{platform}` segment: a snapshot has to live at the path the README renders, and Linux rasterises the same font differently, so the `web-e2e` job skips it exactly as it skips the visual sweep. What changed is that the PNGs are now *derived* — there is a command that makes them, a table that says what each is a picture of, and a diff when they move — where before nothing produced them at all. |
| **R15** — every feature behind a flag | The set is now enumerated in the prose: **nineteen** `enable_*` flags, the **eight** workflow-behavior ones in the table (all off, each independently switchable), and the **eleven** others named — including the four that default *on* and the learning ladder, which is explicitly **not** independent, three of its four flags refusing to construct without the one below them. | `TestTheFlagSet` holds the section against `Settings` in both directions, so a flag added to `src/config.py` and to no document goes red. The enumeration is **reflection over `Settings.model_fields`**, not a checked-in list — WO-D2 re-verified that by adding an undocumented `enable_*` field to a throwaway copy of the tree, which turned two of the six checks red naming the new flag. **Still Partial:** the forward direction — a *feature* with no flag at all — adds no field for a reflection test to see, and the README now says that instead of implying the reverse. |
| **R28** — the nightly eval | "Wired and failing nightly" became "**disabled at the repository** (`disabled_manually`), and every run it did have failed — 54 of 54". The README was the document out of step; `docs/eval.md` and both workflow files already said disabled. | `TestTheNightlyEvalState` holds `README.md`, `docs/eval.md` and both workflow files to one story, and requires a surviving `cron:` to say beside itself that it does not fire — which is the line that would otherwise make a naive test assert the opposite of the truth. **Still Partial:** the state is a GitHub attribute and the run count is Actions history; what is enforced is that the documents agree, never that they are right. |

**The structural reason five of these drifted has been closed.** When this page
was written, no test read `README.md`'s prose: only three touched a README at
all — a `COPY` line, the eval marker block, and the runbooks index — and none
checked a claim.
[`tests/test_documented_claims.py`](../../tests/test_documented_claims.py) is
that missing direction. Its design rule is that **the number lives in the prose
and only there**: every check parses the figure out of the sentence it is about
and compares it against a value re-derived from the artifact, so editing the
sentence is the whole of the edit and there is no second copy to forget. Floor
or equality is then decided per claim, on how the underlying number moves — a
floor where it changes on most pull requests (the Python suite), an equality
where it moves only by a deliberate act (a coverage re-seed, a closed set).

### The README claims

`file:line` is `README.md`.

| # | Line | Claim | What fails when it stops being true | Status |
|---|---|---|---|---|
| R01 | 10 | Pauses for plan approval before spending anything | `tests/test_api_hitl.py::TestHitlPause::test_reaches_pending_review_and_exposes_plan`; the *spend* half in `tests/e2e/test_hitl_review.py::TestPlanReview::test_a_run_parks_for_review_and_shows_the_reviewer_the_plan`, under a zero-spend ledger — and since WO-A13 that tier runs on every PR rather than only from `make test-e2e` | Enforced |
| R02 | 28 | Every stateful concern has a pluggable backend | `tests/test_config.py::TestEnumFieldsAreLiteral::test_every_documented_value_accepted`; `tests/test_workflow_backend_selector.py`; one live suite per backend | Enforced |
| R03 | 29 | Worker leases with a redriver for crash recovery | `tests/test_job_redriver.py::test_orphaned_running_job_is_reclaimed`; `::TestRunnerLeaseUpkeep::test_lease_held_during_run_and_released_after` | Enforced |
| R04 | 30 | "everything emits" JSON logs plus OTel traces and metrics | `tests/test_observability.py::TestJsonFormatter::test_produces_valid_json_line`; `tests/test_log_contract.py::TestTheEventNameSetIsClosed::test_every_event_the_source_emits_is_registered` — but **over-stated**: `enable_tracing` and `enable_metrics` both default off, and `tests/test_otel_metrics.py::TestDisabled::test_configure_installs_no_provider` pins the off state as the shipped one | Partial |
| R05 | 63 | Revisions capped at `max_iterations` | `tests/e2e/test_research_workflow.py::TestFullResearchWorkflow::test_a_critic_that_never_approves_stops_at_the_iteration_ceiling` — the only test of the *fixed pipeline's* cap, and until WO-A13 it ran nowhere but a desk; the supervisor's cap is separately covered by `tests/test_supervisor.py::TestDefaultNextAction::test_revision_ignored_when_iteration_cap_hit` | Enforced |
| R06 | 95 | Strict action enum, budget short-circuits, fail-safe fallback | `tests/test_supervisor.py::TestSupervisorShortCircuits::test_cost_cap_stops_without_llm_call`; `::TestActionEnumInvariants::test_action_to_node_covers_every_action_except_stop` | Enforced |
| R07 | 102 | Browser holds no key; every call same-origin | `web/tests/principal.test.ts` — "is imported only by the proxy route, never by anything a browser loads"; `web/tests/apiProxyRoute.test.ts` | Enforced |
| R08 | 132 | Reattach replays the terminal frame, or `plan_ready` | `tests/test_sse_plan_replay.py::TestPendingReviewReplay::test_first_frame_is_plan_ready`; `tests/test_api_routes.py::TestStreaming::test_stream_of_terminal_job_replays_final_frame` | Enforced |
| R09 | 142 | "Nothing durable lives in a worker's memory" | `tests/test_api_redis_store.py::TestSerialization::test_persistent_fields_excludes_event_queue` proves the *job row* is durable; nothing scans for durable state in module-level globals, so the universal is ungated | Partial |
| R10 | 176 | SSE and HITL resume cross workers, no sticky routing | `tests/test_sse_cross_worker.py::test_events_publish_reaches_subscriber_on_other_worker`; `tests/test_hitl_cross_worker_resume.py::test_cross_worker_resume_wakes_runner` | Enforced |
| R11 | 179 | Local defaults memory/SQLite/disk — the Sprint 1 *storage path*, with byte-identical output explicitly not claimed | `tests/test_config.py::TestDefaults::test_standalone_storage_defaults` asserts the three shipped values; `tests/test_documented_claims.py::TestTheStandaloneDefaults` reads the same three backends out of the sentence and re-derives them from `Settings`' declared defaults, and `::test_none_of_the_three_needs_a_service` names the regression the sentence exists to prevent. **"Byte-identical" was removed rather than mechanised**: nothing here keeps a Sprint 1 artifact to diff against and the outputs are model-generated, so no test could ever have held it — what replaced it is the configuration claim, which is checkable and checked | Enforced |
| R12 | 236 | Contrast-checked in both themes by an axe sweep on every PR | `web/e2e/axe-matrix.spec.ts` — "every §4 state is swept at both narrow widths in both themes", pinning 20 states × 2 themes × 2 widths; `color-contrast` is a gated rule with an empty allowlist; `.github/workflows/ci.yml` runs it per PR | Enforced |
| R13 | 244 | "It works at 390 px" | `web/e2e/reflow.spec.ts` sweeps 320 / 360 / 412 with no horizontal scroll, and device projects run 393 and 412 — **390 itself is tested nowhere.** Bracketed, not measured | Partial |
| R14 | 256 | Screenshots cost nothing to produce, and are Playwright snapshots | `tests/test_documented_claims.py::TestTheScreenshotMechanism` — `web/e2e/fixtures/seed.sh` writes through `psql` and `redis-cli` and issues no `POST` and no `/research`, the stack is pinned to the sentinel the sentence itself names (`web/e2e/support/compose.e2e.yml`), every PNG the README renders is in the tree, and the set the README renders equals the set `web/e2e/readme.spec.ts` captures; `web/tests/ci.test.ts` holds CI's half. The PNGs are now **produced by a run** — `npm run e2e:readme:update`, four consecutive verification runs byte-identical. **The pixel comparison is darwin-only**: the snapshot must live at the path the README renders, which leaves no room for the `{platform}` segment, so the Linux `web-e2e` job skips it as it skips the visual sweep | Partial |
| R15 | 272 | Every post-Sprint-1 feature is behind an independent flag | `tests/test_documented_claims.py::TestTheFlagSet` — the README's flag section and `Settings`' nineteen `enable_*` fields are the same set in *both* directions, the table's eight all default off, each of those eight constructs on its own (which is what "independent" is asserted to mean), and the four flags that default on are the four the prose names. The enumeration is reflection over `Settings.model_fields`, re-verified by WO-D2 against a throwaway tree carrying an extra undocumented flag. **The forward direction stays unheld**: a *feature* shipped with no flag adds no field, and nothing can enumerate features — the same shape of gap as R16's "non-trivial" | Partial |
| R16 | 320 | Every non-trivial decision has an ADR | `tests/test_documented_claims.py::TestTheAdrIndex::test_the_index_and_the_directory_are_the_same_set` (bijection over the 74 files, both directions); `::test_every_adr_the_two_documents_cite_exists`. **"Non-trivial" is a judgement and stays unheld** — the reverse direction is all a test can carry | Partial |
| R17 | 356 | Compose publishes app/web to loopback; Redis and Postgres internal | `tests/test_deployment_contract.py::test_local_host_ports_default_to_loopback` (asserts the literal bind string); `::test_production_only_publishes_the_tls_edge` | Enforced |
| R18 | 411 | `ARXIV_API_KEY` never reaches browser JavaScript | `web/tests/principal.test.ts` — "is the only module that reads ARXIV_API_KEY", walking the tree; `grep NEXT_PUBLIC web/` returns zero hits repo-wide | Enforced |
| R19 | 428 | The endpoint table | `tests/test_contract_openapi_snapshot.py::test_snapshot_covers_every_route_the_frontend_calls` pins 15 paths and their method sets; `tests/test_api_routes.py::TestHealthz::test_healthz_degraded_when_redis_ping_fails` pins "always 200". **Nothing compares the README table to the route set**, so a renamed route leaves the table stale | Partial |
| R20 | 450 | HITL on by default; `hitl_bypass` skips it | `tests/test_api_hitl.py::TestHitlPause::test_reaches_pending_review_and_exposes_plan`; `::test_hitl_bypass_skips_the_pause`. The `enable_hitl=True` default itself is asserted by no test | Enforced |
| R21 | 505 | Concurrency bounded (default 10); job timeout (default 600) | `tests/test_api_routes.py::TestConcurrencyLimit::test_semaphore_serializes_jobs_beyond_ceiling`; `tests/test_runner_cost_cap.py::test_run_job_timeout_fails_the_job`. The *mechanisms* are gated; **the stated defaults are asserted nowhere** | Partial |
| R22 | 514 | Nine parallel CI jobs; over 3,300 Python tests; 3,380 Vitest tests / 155 files | `tests/test_documented_claims.py::TestTheCiJobCount` (the job count against `ci.yml`, plus "no job waits on another" — `needs:` would make *parallel* false without moving the count); `::TestThePythonSuiteCount` (a subprocess collection against the README's floor, and against the floor having fallen more than 500 behind); `::TestTheVitestCounts`. **The Vitest figure is an agreement between two documents**, not a measurement: it is checked against the last coverage re-seed recorded in `web/vitest.config.mts`, and both could be wrong together. Since WO-C2 that source can at least go stale *visibly*, in both of the ways it goes stale: `::test_the_reseed_note_is_the_thresholds_it_seeded` pins the note's `covered/total` counts to the four coverage thresholds seeded under it, so a re-seed that edits the numbers and skips the note fails; `::test_the_recorded_file_count_has_not_fallen_behind_the_tree` bands the note's *file* count against the files on disk, so a note left to age fails too. **Measured while writing that check:** the record (3,380 tests across 155 files) is 97 tests and 3 files behind a real `vitest run` (3,477 across 158). That is within the band and by design — the count of record moves on a coverage re-seed, not on a merge — but it is what "an agreement between two documents" costs, stated as a number rather than as a caveat | Partial |
| R23 | 547 | The audit is a hard gate; every network step is bounded | `web/tests/ci.test.ts` — "runs the dependency audit gate (C4) as its own hard-gating job" (no `continue-on-error`); `web/tests/audit.test.ts` — no env escape, no skip flag, never lowers the level; the install-bounding test counts fetch timeouts. "Every network step" is slightly wider than what is asserted | Enforced |
| R24 | 559 | No `web/` tier makes a paid call; three independent mechanisms | `web/tests/ci.test.ts` — "never gives any job the repository's Anthropic secret" and "hands the e2e stack the disabled sentinel, hard-coded"; `web/e2e/support/global-setup.ts` refuses to start on any other key; `web/e2e/paid-path.spec.ts` pins the browser-side fulfilment | Enforced |
| R25 | 565, 748 | The `e2e` tier is built and gates every PR — sixteen tests, four modules; what is missing is recorded cassettes | `tests/test_documented_claims.py::TestTheE2eTier` — the count as an equality against `pytest -m e2e`, the module count against the directory, `::test_the_marker_and_the_directory_are_the_same_set` (so the count is about a tier and not a folder), and `::test_the_tier_runs_in_ci` on the `make test-e2e` step | Enforced |
| R26 | 596 | Twenty benchmark queries; four LLM-judged metrics in `summary.jsonl` | `tests/test_eval_runner.py::TestSummaryLine::test_extracts_scores_state_and_split_cost_fields` pins the row; `::TestComputeMetrics::test_all_four_scored_and_no_error` pins the metric set. The count test is **`>= 20`**, so a twenty-first query keeps it green while "Twenty" goes stale | Partial |
| R27 | 613 | Per-metric guard, incremental persistence, `--resume`, budget ceiling, distinct exit codes | `tests/test_eval_runner.py::TestComputeMetrics::test_one_failing_judge_does_not_stop_the_others`; `::TestMain::test_records_survive_a_mid_batch_kill`, `::test_resume_skips_completed_queries`, `::test_budget_ceiling_stops_the_campaign`; `::TestExitCode::test_codes_are_distinct` | Enforced |
| R28 | 623 | The nightly is **disabled**; it failed all 54 of the runs it did have; no `summary.jsonl` ever produced | `tests/test_documented_claims.py::TestTheNightlyEvalState` — `README.md`, `docs/eval.md` and both nightly workflow files are held to one story about the disabled state, and a `cron:` that survives in either file has to say beside it that it does not fire. WO-B2 made this possible by having the workflows state their own state in prose; WO-C2 corrected the README, which was the document out of step. **What is enforced is the agreement, not its truth**: `disabled_manually` is a GitHub-side attribute absent from the checkout, so `gh workflow enable` would leave all three documents wrong together, and the 54 runs live in Actions history where no test reaches them | Partial |
| R29 | 653 | `readme_update.py` replaces everything between the markers | `tests/test_readme_update.py::TestPatchReadme::test_replaces_content_between_markers`, plus the missing/swapped-marker cases and the CLI exit code | Enforced |
| R30 | 672 | SDK retries on 408/409/429/5xx, 4 retries, 120 s; `Retry-After` honoured | `tests/test_config.py::TestDefaults::test_anthropic_defaults`; `tests/test_http_session.py::TestBuildRetryingSession::test_respects_retry_after_header`; `tests/test_llm.py::TestGetClient::test_uses_clamped_max_retries`. The status list is SDK-internal and untestable here, and the effective retry count can be **lower** than 4 once clamped | Partial |
| R31 | 680 | Cache-read tokens billed at 10%; the accumulator surfaces the breakdown | `tests/test_observability.py::TestCacheTokenPricing::test_cache_read_priced_at_ten_percent` (1M Sonnet cache-read tokens must cost $0.30 against $3/M); `::TestRunCostsCacheAccumulation::test_as_dict_carries_cache_buckets` | Enforced |
| R32 | 687 | HITL is the first-order cost control — nothing spent before approval | `tests/e2e/test_hitl_review.py::TestPlanReview::test_a_cancelled_review_ends_the_run_without_a_report` — the real graph, zero-spend ledger, `call_count == 0`. **It is the only test that carries the claim, and CI deselects it** | Partial |
| R33 | 688 | Haiku routing: a **modelled** 50-60% cut at a 75-90% routed share, from a price ratio; quality explicitly unmeasured | `tests/test_documented_claims.py::TestTheModelledRoutingSaving::test_haiku_is_one_third_of_sonnet_on_both_token_directions` and `::test_the_readme_band_is_the_arithmetic_it_states`, which recompute the band from `src/observability/costs.py`; `::test_the_readme_still_says_the_saving_is_unmeasured` is a tripwire on the qualifier. **The routed share is still an argument, not a measurement**, and no run here has ever been priced under the mapping | Partial |
| R34 | 689 | Regression diff fails on cost creep > 25%, never exercised on real runs | `tests/test_regression_diff.py::TestResourceBands::test_cost_clearing_both_legs_regresses` and its negative pin the band; `::TestCLI::test_regression_exits_1`. **The shipped gate is narrower than the sentence** — a rise must clear a $0.10 absolute floor *and* 25% relative, so +30% on a $0.20 baseline does not fire | Partial |
| R35 | 692 | Reader falls back to abstract on fetch/extract/chunk/rank failure | `tests/test_reader_fallback_logging.py::TestPerPaperFallbackLine` — one test per named stage; `tests/test_reader.py::TestBuildUserPrompt::test_without_context_notes_fallback` | Enforced |
| R36 | 695 | Every failure mode lands on the `Job` record before propagating | `tests/test_api_hitl.py::TestReviewTimeout::test_hitl_timeout_fails_the_job`; `tests/test_runner_cost_cap.py::test_run_job_timeout_fails_the_job`; `tests/fault/test_cancellation_faults.py::TestCancellationAtShutdown::test_a_shutdown_cancel_is_a_cancelled_job_not_a_failed_one` | Enforced |
| R37 | 696 | TTL'd lease per running job; redriver reclaims orphans | `tests/test_job_redriver.py` (orphan reclaim, live-lease negative, lease upkeep, startup sweep); `tests/fault/test_worker_death_faults.py::TestTheOwnerIsGone::test_a_job_that_already_spent_money_is_failed_never_requeued` | Enforced |
| R38 | 697 | Diagnostics copies the last 200 SSE frames with no question or briefing text | `web/tests/diagnostics/redact.test.ts` — "no question text survives", "no report text survives", against the serialized blob; `web/tests/diagnostics/ring.test.ts` pins `RING_CAPACITY === 200` and the drop order | Enforced |
| R39 | 700 | `run_id` via ContextVars; every call to the accumulator; flags; one WARNING per degradation transition | `tests/test_log_contract.py::TestCorrelationFieldsOnTheLine`; `tests/test_observability.py::TestCurrentCostsAndRecordCall`; `tests/test_health_logging.py::TestTransitionHelper::test_first_failure_warns_once_naming_the_dependency` plus `::test_a_continuing_outage_is_silent` | Enforced |
| R40 | 712 | Untrusted PDF text wrapped and sanitised; `prior_context` too | `tests/test_prompt_isolation.py::TestWrapUntrusted::test_adds_open_and_close_tags`, `::test_escapes_close_tag_inside_content`; `tests/test_reader_isolation.py`; `tests/test_planner_prior_context.py::TestPriorContextIsolation`. **Naming error:** the README writes `<untrusted_paper>`; the shipped tag is `<untrusted_paper_text>` | Enforced |
| R41 | 713 | Verifier flags unsupported claims; evidence store grounds each claim in a chunk | `tests/test_verifier.py::TestSuccessPath::test_unsupported_claim_maps_to_revise_report`; `::TestDossierFromEvidence::test_cited_paper_with_evidence_uses_chunks`; `::TestInvariants::test_verified_true_with_issues_downgrades_to_false` | Enforced |
| R42 | 714 | Constant-time compare; per-key sliding-hour limit; hot-reload keystore | Rate limiting and hot reload are enforced (`tests/test_redis_rate_limiter.py`, `tests/test_keystore_reloader.py`). **The constant-time compare is not tested** — every auth test passes identically with `hmac.compare_digest` replaced by `==`. Timing safety is a code-review fact | Partial |
| R43 | 715 | A key sees only its own jobs and conversations | `tests/test_per_principal_scoping.py` — every job route and every conversation route, cross-principal, 404 not 403; the whole file is `security`-marked | Enforced |
| R44 | 716 | Cost cap between nodes; PDF downloads abort at `pdf_max_bytes` | `tests/test_runner_cost_cap.py::test_run_job_cost_budget_exceeded_fails_the_job`; `tests/test_pdf_parser.py::TestDownloadPdf::test_stops_streaming_when_over_cap`. Enforcement is at **two** layers, not one — the claim is conservative | Enforced |
| R45 | 718 | Auth off by default; the production overlay forces it on | `tests/test_deployment_contract.py::test_production_enforces_both_authentication_layers` (API auth, keyed env, hashed Caddy password); `tests/test_api_auth.py::test_submit_without_key_returns_401`. The default itself is asserted incidentally, in `tests/test_api_error_envelope.py` | Enforced |

### The architecture claims

`file:line` is `docs/architecture.md`.

| # | Line | Claim | What fails when it stops being true | Status |
|---|---|---|---|---|
| A01 | 44 | The browser never holds a credential | `web/tests/principal.test.ts` — sole reader and sole importer, both derived from walking the tree; `web/tests/apiProxyRoute.test.ts` pins the injection point | Enforced |
| A02 | 52 | "The proxy is not optional" | `web/tests/api.test.ts` pins `API_BASE === "/api"`; `web/tests/diagnostics/egress.test.ts` asserts no client file targets another origin. **The premise — that `EventSource` and `<a download>` cannot carry a header — is a browser fact argued in ADR 0055, tested nowhere.** What is enforced is the consequence | Partial |
| A03 | 79 | `revision_target` picks the re-entry node; capped at `max_iterations` | `tests/test_smoke.py::TestRouteAfterCritique::test_valid_target_returns_target`; `tests/test_parse_defense.py::test_invalid_revision_target_downgrades_to_approve` | Enforced |
| A04 | 95 | Strict enum; caps short-circuit before the LLM call; malformed output falls back to rules | `tests/test_supervisor.py::TestActionEnumInvariants::test_action_to_node_covers_every_action_except_stop`; `::TestSupervisorShortCircuits` (both caps); `::TestSupervisorLLMPath::test_invalid_action_falls_back_to_default`; the two flag-gating suites | Enforced |
| A05 | 122 | The graph is built **once** at startup, never per request | `tests/test_workflow_startup_once.py::test_factory_runs_once_at_startup`. **Neither test submits a job**, and a regression that rebuilt inside `run_job` would call `build_workflow` directly rather than the injected factory — so the counter would stay at 1 and both tests would still pass. The per-request-rebuild regression ADR 0034 fixed has no test | Partial |
| A06 | 135 | The middleware: id adoption, echo, correlation context, W3C trace, SERVER span, RED on the route template, one access line | `tests/test_api_middleware.py::TestTheRequestIdIsOneValue`, `::TestTheRedMetrics::test_the_duration_histogram_is_keyed_on_the_route_template`, `::TestInboundTraceContext`, `::TestTheServerSpan`, `::TestTheStructuredAccessLine`, `::TestTheCorrelationContextIsBoundAtTheEdge`. **"Outermost in the stack" is asserted nowhere** — nothing reads `user_middleware`'s order | Partial |
| A07 | 150 | `/healthz` always 200, `/readyz` 503, one latched edge set, `/readyz` out of the contract | `tests/test_api_middleware.py::TestTheHealthReadinessSplit` (all three legs); `tests/test_health_logging.py::TestReadyzSharesTheSameEdges::test_both_endpoints_report_the_same_dependency_body` | Enforced |
| A08 | 162 | 202 immediately; `astream` bounded by semaphore and hard timeout; the lifecycle | `tests/test_api_routes.py::test_submit_returns_202_with_status_and_stream_urls`; `tests/test_bounded_executor_cancel.py::TestLifespanWiring::test_pool_is_sized_to_the_job_ceiling_and_shut_down`; `tests/test_contract_sse_events.py::test_the_web_client_declares_every_job_status_or_declares_the_gap` pins the status vocabulary against the web tier | Enforced |
| A09 | 179 | Five further branches on `job.kind` in `run_job`, each named | `tests/test_documented_claims.py::TestTheJobKindBranches` walks `run_job`'s AST and requires equality with the sentence — the claim is that the set is closed, so a sixth branch fails rather than quietly falsifying the page | Enforced |
| A10 | 202 | One parking shape; research reviews only its first interrupt; a session parks every turn; orphaned parked jobs are failed, never requeued | `tests/test_api_hitl.py::test_second_pause_auto_resumes_without_review`; `tests/test_api_session_lifecycle.py::TestSessionParking::test_every_turn_parks_rather_than_auto_resuming`; `::TestRedriveOfParkedSessions::test_an_orphaned_parked_session_is_failed_never_requeued` | Enforced |
| A11 | 218 | Lifespan-owned pool sized to the ceiling; cancel token before every call; permit held until the thread returns; abandoned threads still counted | `tests/test_bounded_executor_cancel.py::TestRunnerDrain::test_permit_is_held_until_the_node_thread_returns`; `::TestCallSites::test_call_llm_aborts_before_touching_the_client`; `::TestLifespanWiring::test_healthz_counts_abandoned_threads_as_active` | Enforced |
| A12 | 229 | The SSE frame set; parking frames neither terminal nor closing; replay-one-and-close | `tests/test_contract_sse_events.py::test_pinned_set_is_the_documented_union`, `::test_pause_frames_never_end_the_stream`, `::test_attach_replay_reuses_the_runner_terminal_names` | Enforced |
| A13 | 254 | `job_completed` has **one** payload shape; `job_failed`/`job_cancelled` remain a recorded gap | `tests/test_sse_cross_worker.py::test_runner_publishes_terminal_frame_to_other_worker` asserts the live frame is exactly the 11-key union and is `integration`-marked, so it runs in CI. Both halves verified — `docs/observability.md#known-gaps` resolves and records the remaining divergence. (The e2e pair asserts the same union and, since WO-A13, also gates) | Enforced |
| A14 | 266 | Lease, orphan reclaim with `error_type=orphaned`, startup + jittered sweep, `redrive:lock`, compare-and-set | `tests/test_job_redriver.py::test_orphaned_running_job_is_reclaimed`, `::test_redrive_lock_serialises_concurrent_sweeps`, `::test_reclaim_refuses_a_job_that_finished_after_the_reread`; `tests/test_app_periodic_redrive.py` | Enforced |
| A15 | 297 | Provenance non-nullable in the type, the merge and the CHECK constraints; 404 while the flag is off | `tests/test_learner_profile_store.py::TestProvenanceIsNonNullable` (type and read); `::TestDeclarationsSurviveInference::test_the_edit_surface_cannot_forge_provenance` (merge); `tests/test_learn_profile_routes.py::test_every_verb_is_404_while_the_flag_is_off`. **The CHECK-constraint clause is covered only indirectly** — no test executes the DDL and proves the constraint rejects a bad row | Partial |
| A16 | 315 | Two durable sources; a failed snapshot read reports `unavailable` rather than reconstructing | `tests/test_guided_session_graph.py` asserts the available path and that `assessment_status` reports a fact; `tests/test_contract_session_fixtures.py` pins the two-source shape. **The load-bearing half is untested** — no test drives a failing snapshot read, so adding a fallback reconstruction would not go red | Partial |
| A17 | 334 | Every route but the two probes needs a key; cross-principal is 404; per-key sliding hour | `tests/test_api_auth.py::test_submit_without_key_returns_401`; `tests/test_api_middleware.py::TestTheHealthReadinessSplit::test_both_probes_are_auth_exempt`; `tests/test_per_principal_scoping.py` (five cross-principal routes) | Enforced |
| A18 | 362 | Six routes in two groups, pinned against the filesystem | `web/tests/shell/routing.test.ts` — "keeps the workspace routes and adds the parenthesis-free learning URLs", asserting the exact six-route set derived from the filesystem | Enforced |
| A19 | 562 | The storage matrix — setting, options, default, shared-across-workers | `src/config.py`'s `Literal[...]` types reject an out-of-vocabulary value at load; `tests/test_config.py::TestEnumFieldsAreLiteral` pins the option sets. **Nothing reads the table.** The "default first" column, the "shared?" column and the keystore row can all drift; the six defaults are asserted nowhere | Partial |
| A20 | 587 | The image installs the lock, bakes MiniLM, "pinned without a build" | `tests/test_container_contract.py::test_dependencies_come_from_the_lockfile`; `::test_bake_regex_still_matches_the_model_constant` (couples the Dockerfile to `MODEL_NAME`); `::test_no_volume_shadows_the_baked_cache`. All parse the Dockerfile as text and never build — which is exactly what the claim says | Enforced |
| A21 | 596 | `call_llm` is the choke point; envelope clamped to 75% of the job budget; `retries_taken` counted | `tests/test_llm.py::TestRetryEnvelope::test_shipped_defaults_fit_inside_the_job_budget` (the literal 0.75 lives at `src/llm.py:131`); `tests/test_bounded_executor_cancel.py::TestCallSites::test_call_llm_aborts_before_touching_the_client`; `tests/test_otel_metrics.py::TestLlmRetryMetrics` | Enforced |
| A22 | 609 | One retry level per dependency; token bucket; Full Jitter; visible degradation | `tests/test_resilience_transport.py::TestRetriesHappenAtOneLevelOnly::test_a_failing_arxiv_query_costs_exactly_the_configured_attempts` — counts requests at a real socket, so a second retrying level shows 8 or 16 instead of 4; `::TestTheApplicationAddsNoLoopOfItsOwn`; `tests/test_resilience.py::TestTheRetryEnvelopeClamp`, `::TestFullJitter`, `::TestTheSharedBudgetRegistry` | Enforced |
| A23 | 633 | Torch pinned to one thread at load; explicit device | `tests/test_embedding_device.py::TestNativeThreadPinning::test_torch_threads_are_pinned_at_model_load`; `::TestDeviceSelection::test_default_settings_force_cpu`; `::TestLoadLogging::test_device_is_logged_once_at_model_load` | Enforced |
| A24 | 651 | "**twenty-two** OTel instruments" | `tests/test_documented_claims.py::TestTheInstrumentCount` against `tests/test_operability_docs.py`'s AST scan of `src/` — one scan, two readers. That scan's own floor (`>= 20`) is what let "nine" drift for three ADRs; the equality here is what closes it | Enforced |
| A25 | 671 | Eval is **designed to** run nightly in CI with regression diffing, and does not — the workflow is disabled at the repository | `tests/test_documented_claims.py::TestTheNightlyEvalState::test_the_architecture_doc_tells_the_same_story` — no unqualified "runs nightly in CI" survives in this document, and the disabled state is stated rather than left to the qualifier. This was the last **False** row on the page, and it survived WO-B1 and WO-C2 not because the edit was hard but because **no test read this document's nightly sentence**; the row that said its test was "already written" was wrong, and WO-D2 wrote it | Enforced |

---

## What this index found, beyond the counts

Four findings that are properties of the repository rather than of any one
claim.

1. **No test read a prose claim** — **closed by WO-B1.** Five of the eleven
   unenforced rows existed for this one reason: the repository had excellent
   mechanical enforcement of *behaviour* and none of *description*, and
   description is what a reader trusts first.
   [`tests/test_documented_claims.py`](../../tests/test_documented_claims.py)
   now reads both documents. Two things about it are worth carrying into
   whatever reads a claim next. **The number lives in the prose and only
   there** — a figure asserted in both a document and a test is two places to
   update and the second is invisible, so every check parses the number out of
   the sentence and compares it against a value re-derived from the artifact.
   And **floor or equality is a per-claim decision**: a floor where the truth
   moves on most pull requests (an equality on the Python suite size would make
   every PR that adds a test edit the README, which is precisely how the old
   number rotted), an equality where it moves only by a deliberate act, and a
   *band* on the floor so that a floor left far behind the truth also fails.
2. **The `e2e` tier was dark in CI until the PR before this one.** For most of
   this index's drafting, `.github/workflows/ci.yml` ran `pytest -m "not e2e"`
   and nothing else selected the tier — so R01, R05 and R32, including
   "nothing is spent before you approve the plan", had their strongest
   assertion in a tier no pull request ran. WO-A13 closed it: the tier, the
   coverage floors, patch coverage and the adversarial suite are all steps in
   the `tests` job now. The residual is recorded in that workflow's own
   comments and is worth repeating here, because it is the same species of
   gap: `property`, `fault` and `security` gate only because they sit *inside*
   the `-m "not e2e"` selection, so a tier that stopped selecting anything
   would still be silent. A marker census beside the tier census in
   `tests/test_harness_guards.py` is what closes it.
3. **Two documents in this repository contradict each other about the nightly
   eval**, and nothing notices (R28, A25) — **closed for R28 by WO-C2**, in
   two steps that are worth separating. WO-B2 made both nightly workflow
   files say in prose what the checkout cannot show: that they are disabled
   at the repository, that `disabled_manually` is a GitHub-side attribute,
   and that the `cron:` each one still carries does not fire. That turned an
   unreadable fact into a readable one. WO-C2 then corrected `README.md` —
   the document that was out of step — and added
   `TestTheNightlyEvalState`, which holds the README, `docs/eval.md` and both
   workflow files to one story and requires a surviving `cron:` to keep the
   sentence that explains it. **WO-D2 closed A25 too**, and the reason it was
   still open is worth recording: correcting the sentence was a one-line
   edit, but nothing in this repository read `docs/architecture.md`'s nightly
   sentence, so the row above claiming "the test is already written" was
   describing a test that did not exist. The story is now told the same way
   by four artifacts and a fifth test holds the fourth to it. The residue is
   exactly the part that was never in the tree: enabling the workflow with
   `gh workflow enable` makes all four documents wrong at once and no test
   can see it.
4. **The four claims most likely to be believed were the four with the least
   behind them**: the test counts (R22), the routing cost saving (R33), the
   instrument count (A24), and "runs nightly" (A25). Numbers read as measured
   whether or not anything measured them — and R22 went stale twice during the
   week this page was written, once from a peer's work and once from its own.
   **All four now have a test behind them**, A25 last, and none of the four
   sentences was weakened to get there: A25's says what the workflow is
   designed to do *and* that it does not run, which is longer than the
   sentence it replaced rather than shorter. What no test can reach is
   unchanged — A25's truth lives in GitHub's repository settings and not in
   the tree — so its row is Enforced on the agreement between four documents
   and says so.
5. **A count of record ages even when nothing is wrong.** R22's Vitest figure
   moves only on a coverage re-seed, which is deliberate, and the band around
   it is what separates designed lag from abandonment. WO-C2 predicted the
   gap and WO-D2 measured it: 3,380 across 155 recorded against 3,477 across
   158 actual, on a `git archive` of origin/main. The record was re-seeded
   and **the coverage thresholds deliberately were not** — three of the four
   columns had moved by 0.00-0.05, and the fourth swung 0.19 across three
   runs of the column `web/vitest.config.mts` already documents as the
   unstable one. A floor raised to within less than its own noise is a floor
   that goes red on somebody else's pull request.

Findings 1 and 4 are addressed above. WO-A14 documented them and owned no
prose; **WO-B1** owned `README.md`, `docs/architecture.md` and the new claims
file, and closed what it could; **WO-C2** owned `README.md`, `docs/eval.md`,
the two nightly workflows and the claims file, and closed finding 3 and the
four remaining unenforced rows. **Finding 2 remains**, with a name attached:
`property`, `fault` and `security` gate only because they sit inside the
`-m "not e2e"` selection, and a marker census in
`tests/test_harness_guards.py` is what would close it.

## Related

- `docs/testing.md` — the tiers, what fails each one, and the local equivalents.
- `docs/reliability.md` — the SLIs, the error budgets, and what cannot be measured yet.
- `docs/security.md` — the threat model behind §6 of the system card.
- `docs/eval.md` — the benchmark, the metrics, and the campaign run-book.
- [`../../planning/08-assurance/STATUS.md`](../../planning/08-assurance/STATUS.md) — the phase record, the defect register, and the corrections this campaign made to its own plan.
