# Assurance

The index. Open this, and every claim this repository makes about reliability,
safety, accuracy and compliance leads to the artifact that enforces it — or to a
plain statement that nothing does.

**Reviewed at `ed71098`.** Every path cited on this page and in
[`framework-mapping.md`](framework-mapping.md) resolves at that commit, and
`tests/test_assurance_docs.py` fails when one stops resolving. A crosswalk full
of dead links is worse than no crosswalk.

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
3. [The eleven claims that nothing enforces](#the-eleven-claims-nothing-enforces),
   below — including five that are **false on this tree**.
4. [`framework-mapping.md`](framework-mapping.md) §6 — the ten things that
   cannot be measured here, each with the constraint that makes it so.

---

## Claim → enforcement index

**70 claims** were extracted from `README.md` (45) and `docs/architecture.md`
(25). For each: what fails when it stops being true.

| Status | Count | Means |
|---|---|---|
| **Enforced** | 44 | A named test, gate or validator goes red. |
| **Partial** | 15 | Something goes red, but narrower than the claim. The gap is named. |
| **Not enforced** | 6 | Nothing goes red. |
| **False** | 5 | The claim is untrue on this tree. Also unenforced, by definition. |

The last two rows are the valuable part of this document. A claim nothing
enforces is a claim that will drift, and five already have.

### The eleven claims nothing enforces

Read this list before the full table.

| Claim | Where | Why it matters |
|---|---|---|
| **R33** — cost-aware routing gives "~50-60% cost cut with baseline quality preserved" | `README.md:611` | **The only numeric accuracy/efficiency claim in the README, and there is no measurement anywhere in the repository.** The strings "50-60" and "cost cut" appear only in that sentence; ADR 0021 explicitly defers the evidence to "paired-diff eval runs" that have never happened. "Quality preserved" has no measurement at all. |
| **R22** — the test counts | `README.md:479-486` | **Half fixed, half false, and freshly stale.** WO-A13 corrected the Python figure to 3,277 in the same PR that made every tier gate — and this work order's 29 new tests moved it again, to **3,306** collected (3,235 passed and 55 skipped in `-m "not e2e"`, plus 16 `e2e`). The web figures were not touched and remain wrong: "2,970 Vitest tests across 136 files" is at least two re-seeds behind `web/vitest.config.mts`'s own note ("3,380 tests across 155 files"). "Nine parallel jobs" is true — nine job keys, no `needs:`, and WO-A13 kept it nine on purpose. **A number nothing checks goes stale on the next PR, and this row is the demonstration: it went stale twice while this document was being written.** |
| **R25** — the Python `e2e` tier is "registered but not built"; "the marker is registered and unused" | `README.md:513-517`, `:671` | **False.** The tier exists: 16 tests across four modules under `tests/e2e/`, with a shared harness and committed inputs. `docs/testing.md` was already corrected; `README.md` was left behind. The *cassette* half survives literally — the tier uses mock mode and canned agent output by decision, not cassettes. And since WO-A13 the tier runs on every PR (`make test-e2e`, ~5 s), so "registered and unused" is now false twice over. |
| **A09** — "nothing else in `run_job` branches on the kind" | `docs/architecture.md:179` | **False.** `run_job` branches on `job.kind` in at least five further places beyond the four `JobKindRuntime` decisions — the cost cap, a per-node cost log, progress-event persistence, the profile write, and cost-cap behaviour. It is also prose: no AST scan, no lint rule, nothing structural. |
| **A24** — "**nine** OTel instruments behind `enable_metrics`" | `docs/architecture.md:643` | **False.** Measured **21**, by the same AST technique `tests/test_operability_docs.py` uses. The doc's nine is a strict subset — it omits the queue-wait histogram, the seven-instrument GenAI family, the two HTTP RED instruments, and two of four gauges. The scan asserts `len(INSTRUMENTS) >= 20`: a floor, not a fixture, which is exactly why "nine" drifted. |
| **A25** — eval "run nightly in CI with regression diffing" | `docs/architecture.md:658-659` | **False.** `eval-nightly.yml` is disabled (`disabled_manually`) and stays that way pending the funding decision; the README says separately that no campaign has ever produced a `summary.jsonl`. Nothing asserts the workflow's state either way. Honest wording: *designed to run nightly; disabled pending funding*. |
| **R28** — "failed all 54 of its runs"; "no campaign has ever produced a `summary.jsonl`" | `README.md:558-564` | Unenforceable from the tree — the run count lives in GitHub Actions history. **And already drifting:** the README describes the workflow as wired and still failing nightly, while `docs/eval.md` says it is disabled; the workflow file itself still carries a live `cron`. Two documents in one repository disagree, and nothing notices. |
| **R11** — outside compose the defaults are memory / SQLite / disk, "so Sprint 1 behavior stays byte-identical" | `README.md:179-182` | The defaults exist only as Pydantic field values; no test asserts any of the three. "Byte-identical" has no artifact of any kind. Three lines in `tests/test_config.py::TestDefaults` would close the first half. |
| **R14** — the screenshots were produced at zero spend, fixtures written straight into Postgres and Redis | `README.md:249-254` | The *mechanism* is real and gated — the seed script never calls `POST /research`, CI hands the e2e stack a hard-coded disabled sentinel, and `global-setup.ts` refuses to start otherwise. But nothing binds the committed PNGs to any run. Capturing them as Playwright snapshots would make a regeneration a diff. |
| **R15** — "Every feature added after Sprint 1 is behind an independent flag" | `README.md:258-260` | Every flag in the table does default off, and individual flags have gating tests. Nothing enumerates the set, so a *new* feature shipped unflagged goes undetected. A reflection test over `Settings`' `enable_*` fields would close it. |
| **R16** — "Every non-trivial decision in this repo has an ADR" | `README.md:285-287` | **No test reads `docs/decisions/` at all.** 74 ADRs, and nothing checks the index against the directory. "Non-trivial" is not mechanisable, but the reverse direction is: assert the index lists every `NNNN-*.md`, and that every ADR linked from a doc exists. |

**The structural reason five of these drifted:** no test reads `README.md`'s
prose. Only three tests touch a README at all — a `COPY` line, the eval marker
block, and the runbooks index — and none checks a claim. That is one finding,
not five.

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
| R11 | 179 | Local defaults memory/SQLite/disk, "byte-identical" | **Nothing.** See above. | Not enforced |
| R12 | 229 | Contrast-checked in both themes by an axe sweep on every PR | `web/e2e/axe-matrix.spec.ts` — "every §4 state is swept at both narrow widths in both themes", pinning 20 states × 2 themes × 2 widths; `color-contrast` is a gated rule with an empty allowlist; `.github/workflows/ci.yml` runs it per PR | Enforced |
| R13 | 237 | "It works at 390 px" | `web/e2e/reflow.spec.ts` sweeps 320 / 360 / 412 with no horizontal scroll, and device projects run 393 and 412 — **390 itself is tested nowhere.** Bracketed, not measured | Partial |
| R14 | 249 | Screenshots cost nothing to produce | **Nothing binds the PNGs to a run.** See above. | Not enforced |
| R15 | 258 | Every post-Sprint-1 feature is behind an independent flag | **Nothing enumerates the set.** See above. | Not enforced |
| R16 | 285 | Every non-trivial decision has an ADR | **No test reads `docs/decisions/`.** See above. | Not enforced |
| R17 | 321 | Compose publishes app/web to loopback; Redis and Postgres internal | `tests/test_deployment_contract.py::test_local_host_ports_default_to_loopback` (asserts the literal bind string); `::test_production_only_publishes_the_tls_edge` | Enforced |
| R18 | 376 | `ARXIV_API_KEY` never reaches browser JavaScript | `web/tests/principal.test.ts` — "is the only module that reads ARXIV_API_KEY", walking the tree; `grep NEXT_PUBLIC web/` returns zero hits repo-wide | Enforced |
| R19 | 393 | The endpoint table | `tests/test_contract_openapi_snapshot.py::test_snapshot_covers_every_route_the_frontend_calls` pins 15 paths and their method sets; `tests/test_api_routes.py::TestHealthz::test_healthz_degraded_when_redis_ping_fails` pins "always 200". **Nothing compares the README table to the route set**, so a renamed route leaves the table stale | Partial |
| R20 | 415 | HITL on by default; `hitl_bypass` skips it | `tests/test_api_hitl.py::TestHitlPause::test_reaches_pending_review_and_exposes_plan`; `::test_hitl_bypass_skips_the_pause`. The `enable_hitl=True` default itself is asserted by no test | Enforced |
| R21 | 470 | Concurrency bounded (default 10); job timeout (default 600) | `tests/test_api_routes.py::TestConcurrencyLimit::test_semaphore_serializes_jobs_beyond_ceiling`; `tests/test_runner_cost_cap.py::test_run_job_timeout_fails_the_job`. The *mechanisms* are gated; **the stated defaults are asserted nowhere** | Partial |
| R22 | 479 | Nine CI jobs; 1,447 Python tests; 2,970 Vitest tests / 136 files | Nine jobs is true. **The two counts are false.** See above | **False** |
| R23 | 495 | The audit is a hard gate; every network step is bounded | `web/tests/ci.test.ts` — "runs the dependency audit gate (C4) as its own hard-gating job" (no `continue-on-error`); `web/tests/audit.test.ts` — no env escape, no skip flag, never lowers the level; the install-bounding test counts fetch timeouts. "Every network step" is slightly wider than what is asserted | Enforced |
| R24 | 507 | No `web/` tier makes a paid call; three independent mechanisms | `web/tests/ci.test.ts` — "never gives any job the repository's Anthropic secret" and "hands the e2e stack the disabled sentinel, hard-coded"; `web/e2e/support/global-setup.ts` refuses to start on any other key; `web/e2e/paid-path.spec.ts` pins the browser-side fulfilment | Enforced |
| R25 | 511, 659 | The Python `e2e` tier is registered but not built | **False.** See above | **False** |
| R26 | 531 | Twenty benchmark queries; four LLM-judged metrics in `summary.jsonl` | `tests/test_eval_runner.py::TestSummaryLine::test_extracts_scores_state_and_split_cost_fields` pins the row; `::TestComputeMetrics::test_all_four_scored_and_no_error` pins the metric set. The count test is **`>= 20`**, so a twenty-first query keeps it green while "Twenty" goes stale | Partial |
| R27 | 548 | Per-metric guard, incremental persistence, `--resume`, budget ceiling, distinct exit codes | `tests/test_eval_runner.py::TestComputeMetrics::test_one_failing_judge_does_not_stop_the_others`; `::TestMain::test_records_survive_a_mid_batch_kill`, `::test_resume_skips_completed_queries`, `::test_budget_ceiling_stops_the_campaign`; `::TestExitCode::test_codes_are_distinct` | Enforced |
| R28 | 558 | The nightly failed all 54 runs; no `summary.jsonl` ever produced | **Nothing, and it contradicts `docs/eval.md`.** See above | Not enforced |
| R29 | 576 | `readme_update.py` replaces everything between the markers | `tests/test_readme_update.py::TestPatchReadme::test_replaces_content_between_markers`, plus the missing/swapped-marker cases and the CLI exit code | Enforced |
| R30 | 595 | SDK retries on 408/409/429/5xx, 4 retries, 120 s; `Retry-After` honoured | `tests/test_config.py::TestDefaults::test_anthropic_defaults`; `tests/test_http_session.py::TestBuildRetryingSession::test_respects_retry_after_header`; `tests/test_llm.py::TestGetClient::test_uses_clamped_max_retries`. The status list is SDK-internal and untestable here, and the effective retry count can be **lower** than 4 once clamped | Partial |
| R31 | 603 | Cache-read tokens billed at 10%; the accumulator surfaces the breakdown | `tests/test_observability.py::TestCacheTokenPricing::test_cache_read_priced_at_ten_percent` (1M Sonnet cache-read tokens must cost $0.30 against $3/M); `::TestRunCostsCacheAccumulation::test_as_dict_carries_cache_buckets` | Enforced |
| R32 | 610 | HITL is the first-order cost control — nothing spent before approval | `tests/e2e/test_hitl_review.py::TestPlanReview::test_a_cancelled_review_ends_the_run_without_a_report` — the real graph, zero-spend ledger, `call_count == 0`. **It is the only test that carries the claim, and CI deselects it** | Partial |
| R33 | 611 | Haiku routing: "~50-60% cost cut with baseline quality preserved" | **Nothing. No measurement exists.** See above | Not enforced |
| R34 | 612 | Regression diff fails on cost creep > 25%, never exercised on real runs | `tests/test_regression_diff.py::TestResourceBands::test_cost_clearing_both_legs_regresses` and its negative pin the band; `::TestCLI::test_regression_exits_1`. **The shipped gate is narrower than the sentence** — a rise must clear a $0.10 absolute floor *and* 25% relative, so +30% on a $0.20 baseline does not fire | Partial |
| R35 | 615 | Reader falls back to abstract on fetch/extract/chunk/rank failure | `tests/test_reader_fallback_logging.py::TestPerPaperFallbackLine` — one test per named stage; `tests/test_reader.py::TestBuildUserPrompt::test_without_context_notes_fallback` | Enforced |
| R36 | 618 | Every failure mode lands on the `Job` record before propagating | `tests/test_api_hitl.py::TestReviewTimeout::test_hitl_timeout_fails_the_job`; `tests/test_runner_cost_cap.py::test_run_job_timeout_fails_the_job`; `tests/fault/test_cancellation_faults.py::TestCancellationAtShutdown::test_a_shutdown_cancel_is_a_cancelled_job_not_a_failed_one` | Enforced |
| R37 | 619 | TTL'd lease per running job; redriver reclaims orphans | `tests/test_job_redriver.py` (orphan reclaim, live-lease negative, lease upkeep, startup sweep); `tests/fault/test_worker_death_faults.py::TestTheOwnerIsGone::test_a_job_that_already_spent_money_is_failed_never_requeued` | Enforced |
| R38 | 620 | Diagnostics copies the last 200 SSE frames with no question or briefing text | `web/tests/diagnostics/redact.test.ts` — "no question text survives", "no report text survives", against the serialized blob; `web/tests/diagnostics/ring.test.ts` pins `RING_CAPACITY === 200` and the drop order | Enforced |
| R39 | 623 | `run_id` via ContextVars; every call to the accumulator; flags; one WARNING per degradation transition | `tests/test_log_contract.py::TestCorrelationFieldsOnTheLine`; `tests/test_observability.py::TestCurrentCostsAndRecordCall`; `tests/test_health_logging.py::TestTransitionHelper::test_first_failure_warns_once_naming_the_dependency` plus `::test_a_continuing_outage_is_silent` | Enforced |
| R40 | 635 | Untrusted PDF text wrapped and sanitised; `prior_context` too | `tests/test_prompt_isolation.py::TestWrapUntrusted::test_adds_open_and_close_tags`, `::test_escapes_close_tag_inside_content`; `tests/test_reader_isolation.py`; `tests/test_planner_prior_context.py::TestPriorContextIsolation`. **Naming error:** the README writes `<untrusted_paper>`; the shipped tag is `<untrusted_paper_text>` | Enforced |
| R41 | 636 | Verifier flags unsupported claims; evidence store grounds each claim in a chunk | `tests/test_verifier.py::TestSuccessPath::test_unsupported_claim_maps_to_revise_report`; `::TestDossierFromEvidence::test_cited_paper_with_evidence_uses_chunks`; `::TestInvariants::test_verified_true_with_issues_downgrades_to_false` | Enforced |
| R42 | 637 | Constant-time compare; per-key sliding-hour limit; hot-reload keystore | Rate limiting and hot reload are enforced (`tests/test_redis_rate_limiter.py`, `tests/test_keystore_reloader.py`). **The constant-time compare is not tested** — every auth test passes identically with `hmac.compare_digest` replaced by `==`. Timing safety is a code-review fact | Partial |
| R43 | 638 | A key sees only its own jobs and conversations | `tests/test_per_principal_scoping.py` — every job route and every conversation route, cross-principal, 404 not 403; the whole file is `security`-marked | Enforced |
| R44 | 639 | Cost cap between nodes; PDF downloads abort at `pdf_max_bytes` | `tests/test_runner_cost_cap.py::test_run_job_cost_budget_exceeded_fails_the_job`; `tests/test_pdf_parser.py::TestDownloadPdf::test_stops_streaming_when_over_cap`. Enforcement is at **two** layers, not one — the claim is conservative | Enforced |
| R45 | 641 | Auth off by default; the production overlay forces it on | `tests/test_deployment_contract.py::test_production_enforces_both_authentication_layers` (API auth, keyed env, hashed Caddy password); `tests/test_api_auth.py::test_submit_without_key_returns_401`. The default itself is asserted incidentally, in `tests/test_api_error_envelope.py` | Enforced |

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
| A09 | 179 | "nothing else in `run_job` branches on the kind" | **False, and prose.** See above | **False** |
| A10 | 194 | One parking shape; research reviews only its first interrupt; a session parks every turn; orphaned parked jobs are failed, never requeued | `tests/test_api_hitl.py::test_second_pause_auto_resumes_without_review`; `tests/test_api_session_lifecycle.py::TestSessionParking::test_every_turn_parks_rather_than_auto_resuming`; `::TestRedriveOfParkedSessions::test_an_orphaned_parked_session_is_failed_never_requeued` | Enforced |
| A11 | 210 | Lifespan-owned pool sized to the ceiling; cancel token before every call; permit held until the thread returns; abandoned threads still counted | `tests/test_bounded_executor_cancel.py::TestRunnerDrain::test_permit_is_held_until_the_node_thread_returns`; `::TestCallSites::test_call_llm_aborts_before_touching_the_client`; `::TestLifespanWiring::test_healthz_counts_abandoned_threads_as_active` | Enforced |
| A12 | 221 | The SSE frame set; parking frames neither terminal nor closing; replay-one-and-close | `tests/test_contract_sse_events.py::test_pinned_set_is_the_documented_union`, `::test_pause_frames_never_end_the_stream`, `::test_attach_replay_reuses_the_runner_terminal_names` | Enforced |
| A13 | 246 | `job_completed` has **one** payload shape; `job_failed`/`job_cancelled` remain a recorded gap | `tests/test_sse_cross_worker.py::test_runner_publishes_terminal_frame_to_other_worker` asserts the live frame is exactly the 11-key union and is `integration`-marked, so it runs in CI. Both halves verified — `docs/observability.md#known-gaps` resolves and records the remaining divergence. (The e2e pair asserts the same union and, since WO-A13, also gates) | Enforced |
| A14 | 258 | Lease, orphan reclaim with `error_type=orphaned`, startup + jittered sweep, `redrive:lock`, compare-and-set | `tests/test_job_redriver.py::test_orphaned_running_job_is_reclaimed`, `::test_redrive_lock_serialises_concurrent_sweeps`, `::test_reclaim_refuses_a_job_that_finished_after_the_reread`; `tests/test_app_periodic_redrive.py` | Enforced |
| A15 | 289 | Provenance non-nullable in the type, the merge and the CHECK constraints; 404 while the flag is off | `tests/test_learner_profile_store.py::TestProvenanceIsNonNullable` (type and read); `::TestDeclarationsSurviveInference::test_the_edit_surface_cannot_forge_provenance` (merge); `tests/test_learn_profile_routes.py::test_every_verb_is_404_while_the_flag_is_off`. **The CHECK-constraint clause is covered only indirectly** — no test executes the DDL and proves the constraint rejects a bad row | Partial |
| A16 | 307 | Two durable sources; a failed snapshot read reports `unavailable` rather than reconstructing | `tests/test_guided_session_graph.py` asserts the available path and that `assessment_status` reports a fact; `tests/test_contract_session_fixtures.py` pins the two-source shape. **The load-bearing half is untested** — no test drives a failing snapshot read, so adding a fallback reconstruction would not go red | Partial |
| A17 | 326 | Every route but the two probes needs a key; cross-principal is 404; per-key sliding hour | `tests/test_api_auth.py::test_submit_without_key_returns_401`; `tests/test_api_middleware.py::TestTheHealthReadinessSplit::test_both_probes_are_auth_exempt`; `tests/test_per_principal_scoping.py` (five cross-principal routes) | Enforced |
| A18 | 354 | Six routes in two groups, pinned against the filesystem | `web/tests/shell/routing.test.ts` — "keeps the workspace routes and adds the parenthesis-free learning URLs", asserting the exact six-route set derived from the filesystem | Enforced |
| A19 | 554 | The storage matrix — setting, options, default, shared-across-workers | `src/config.py`'s `Literal[...]` types reject an out-of-vocabulary value at load; `tests/test_config.py::TestEnumFieldsAreLiteral` pins the option sets. **Nothing reads the table.** The "default first" column, the "shared?" column and the keystore row can all drift; the six defaults are asserted nowhere | Partial |
| A20 | 579 | The image installs the lock, bakes MiniLM, "pinned without a build" | `tests/test_container_contract.py::test_dependencies_come_from_the_lockfile`; `::test_bake_regex_still_matches_the_model_constant` (couples the Dockerfile to `MODEL_NAME`); `::test_no_volume_shadows_the_baked_cache`. All parse the Dockerfile as text and never build — which is exactly what the claim says | Enforced |
| A21 | 588 | `call_llm` is the choke point; envelope clamped to 75% of the job budget; `retries_taken` counted | `tests/test_llm.py::TestRetryEnvelope::test_shipped_defaults_fit_inside_the_job_budget` (the literal 0.75 lives at `src/llm.py:131`); `tests/test_bounded_executor_cancel.py::TestCallSites::test_call_llm_aborts_before_touching_the_client`; `tests/test_otel_metrics.py::TestLlmRetryMetrics` | Enforced |
| A22 | 601 | One retry level per dependency; token bucket; Full Jitter; visible degradation | `tests/test_resilience_transport.py::TestRetriesHappenAtOneLevelOnly::test_a_failing_arxiv_query_costs_exactly_the_configured_attempts` — counts requests at a real socket, so a second retrying level shows 8 or 16 instead of 4; `::TestTheApplicationAddsNoLoopOfItsOwn`; `tests/test_resilience.py::TestTheRetryEnvelopeClamp`, `::TestFullJitter`, `::TestTheSharedBudgetRegistry` | Enforced |
| A23 | 625 | Torch pinned to one thread at load; explicit device | `tests/test_embedding_device.py::TestNativeThreadPinning::test_torch_threads_are_pinned_at_model_load`; `::TestDeviceSelection::test_default_settings_force_cpu`; `::TestLoadLogging::test_device_is_logged_once_at_model_load` | Enforced |
| A24 | 643 | "**nine** OTel instruments" | **False — measured 21.** See above | **False** |
| A25 | 656 | Eval runs nightly in CI with regression diffing | **False — the workflow is disabled.** See above | **False** |

---

## What this index found, beyond the counts

Four findings that are properties of the repository rather than of any one
claim.

1. **No test reads a prose claim.** Five of the eleven unenforced rows exist for
   this one reason. The repository has excellent mechanical enforcement of
   *behaviour* and none of *description*, and description is what a reader
   trusts first.
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
   eval**, and nothing notices (R28, A25).
4. **The four claims most likely to be believed are the four with the least
   behind them**: the test counts (R22), the routing cost saving (R33), the
   instrument count (A24), and "runs nightly" (A25). Numbers read as measured
   whether or not anything measured them — and R22 went stale twice during the
   week this page was written, once from a peer's work and once from its own.

None of these is fixed here. WO-A14 documents; it does not own `README.md`
beyond a pointer, `docs/architecture.md`, or the CI workflow. Each is stated so
the next work order can pick it up with a name attached.

## Related

- `docs/testing.md` — the tiers, what fails each one, and the local equivalents.
- `docs/reliability.md` — the SLIs, the error budgets, and what cannot be measured yet.
- `docs/security.md` — the threat model behind §6 of the system card.
- `docs/eval.md` — the benchmark, the metrics, and the campaign run-book.
- [`../../planning/08-assurance/STATUS.md`](../../planning/08-assurance/STATUS.md) — the phase record, the defect register, and the corrections this campaign made to its own plan.
