# Agent-capability work orders

Status: **WAVE 1 AUTHORIZED (CAP-01, CAP-02) — 2026-09-05**

Both wave-1 work orders are independent and run concurrently. Each is
default-off, zero-spend, and lands a golden test proving that default
settings leave today's behaviour byte-identical.

## CAP-01 — Model-aware request profiles in the gateway

### Measured problem (on `origin/main`, 2026-09-05)

- `src/llm.py` sends `temperature=_TEMPERATURE` (0.3) on every call. Opus
  4.7 and later, Opus 5, Sonnet 5, and Fable 5 reject sampling parameters
  with HTTP 400; the default `claude-sonnet-4-6` still accepts them, so the
  gateway breaks the day the model id changes.
- `call_llm_json` obtains JSON by `json.loads` on free text with a
  `strict=False` fallback. Every structured agent (planner, critic,
  supervisor, verifier, query refiner, assessment) pays a parse-failure and
  retry path that native structured outputs remove.
- No call uses adaptive thinking or `effort`. The adaptive-compute section
  of the target architecture never names this lever, yet it is the cheapest
  test-time-compute knob the system has.
- Response parsing assumes the first content block is text. With thinking
  enabled the first block is a `thinking` block, so enabling thinking today
  would return empty text.
- The installed SDK (`anthropic==0.116.0`, pinned in both lockfiles) already
  ships `output_config`, `effort`, adaptive thinking, and `messages.parse`.
  No dependency change is needed for this work order.

### Deliverables

1. **Capability table.** A pure module (proposed `src/llm_models.py`) that
   maps a model id to `ModelCapabilities(sampling_params: bool,
   adaptive_thinking: bool, effort: bool, structured_outputs: bool)`. Rows
   for every id the price table in `src/observability/costs.py` knows, plus
   family-prefix fallbacks. Unknown ids resolve to the conservative row: no
   sampling params sent, no thinking, no effort, no structured outputs, and
   one `WARNING` log per process naming the id. Each row cites its source in
   a comment. Property test: every id in `resolved_model_ids()` resolves to a
   non-fallback row.
2. **Request profile.** A frozen `RequestProfile(thinking, effort,
   structured_outputs, temperature)` resolved per call from new additive
   `Settings` fields, all defaulting to today's behaviour:
   - `llm_thinking: Literal["off", "adaptive"] = "off"`
   - `llm_effort: Literal["", "low", "medium", "high", "xhigh", "max"] = ""`
   - per-agent overrides `<agent>_effort` for planner, reader, synthesizer,
     critic, verifier, supervisor, query_refiner, tutor, assessment,
     mirroring the existing `<agent>_model` fields; empty inherits.
   - `enable_structured_outputs: bool = False`
   - `llm_temperature: float = 0.3` (bounded 0–1), sent only when the
     capability row allows sampling params.
   Validation at settings load: an `llm_effort` or `llm_thinking` other than
   the default on a model whose row lacks the capability fails with a
   `ValueError` naming the field and the model.
3. **Gateway changes in `src/llm.py`.** `call_llm` builds kwargs from the
   profile: `thinking={"type": "adaptive"}` and `output_config={"effort": ...}`
   only when enabled and supported; `temperature` only when supported.
   Response text is the concatenation of `text` blocks; `thinking` blocks are
   skipped, never logged. `call_llm_json` gains an optional
   `schema: type[pydantic.BaseModel] | None`; when `enable_structured_outputs`
   is on, the row allows it, and a schema is given, the call uses the SDK's
   structured-output path (read the installed SDK source under
   `.venv/lib/python3.13/site-packages/anthropic/resources/messages/` for the
   exact 0.116.0 API; do not guess from memory) and returns the validated
   dict; otherwise the existing parse path runs unchanged. The span attribute
   `gen_ai.request.temperature` (ADR 0066) reports what was actually sent, or
   is absent when nothing was. That change must stay inside `src/llm.py`;
   `src/observability/**` is fenced for Puma's W05–W08. If the attribute
   cannot be made truthful without editing the fenced package, stop and
   report the exact lines instead of editing them.
4. **First schema consumers.** Pydantic schemas for the planner, critic,
   supervisor, and verifier outputs, derived from the shapes those agents
   already validate by hand. Prompt text unchanged. Callers pass the schema;
   with the flag off nothing changes.
5. **Cost accounting.** Thinking tokens are output tokens; verify the
   existing usage path counts them and that cache-read and cache-creation
   tokens remain separate. `RunCosts` shape unchanged.
6. **ADR** "Model-aware request profiles in the LLM gateway": context above,
   the capability table as the single place model quirks live, why prompt
   text is untouched, what is unverified without a live call.
7. **Docs.** `.env.example` entries for the new settings; a short
   "Request profiles" section in the gateway's existing documentation
   (`docs/architecture.md` additive, or `docs/agents/README.md`).

### Tests (all zero-network, using the harness fake client)

- Golden: default settings produce kwargs identical to a checked-in fixture
  captured from today's `call_llm` for a text call and a JSON call.
- Matrix over `claude-sonnet-4-6`, `claude-haiku-4-5`, `claude-opus-5`,
  `claude-sonnet-5`, and an unknown id: which of `temperature`, `thinking`,
  `output_config` appear.
- Thinking-block parsing: a fake response `[thinking, text, text]` returns
  the joined text; a `[thinking]`-only response raises the existing
  upstream-output error, not an empty string.
- Structured path: a fake parsed response returns the validated dict; a
  fake schema violation raises the existing `UpstreamModelOutput` family
  (ADR 0064) with a stable code.
- Settings validation: each invalid combination fails at load with the
  documented message.
- Property: every model id the price table knows resolves to a real row.
- Existing suites green: `pytest -m "not e2e" -q`, `pytest -m security -q`,
  `pytest -m property -q`, `ruff check .`, `mypy --strict src/`.

### Acceptance

- Flags off: golden kwargs identical; full suite green.
- Flags on with the default model: adaptive thinking, effort, and
  temperature sent; text parsing skips thinking blocks.
- Flags on with an Opus 5 id: no `temperature`; thinking and effort sent.
- Flags on with Haiku 4.5: temperature sent; no thinking, no effort.
- `enable_structured_outputs` on: the four schema consumers get validated
  dicts; the free-text parse path is not reached for them.
- The PR body states plainly that behaviour with the real model is not
  verified until CAP-06.

### Not in scope

Changing the default model id, the SDK version, any prompt wording, the
judges in `src/eval/**`, or the learning-lane agents beyond the effort
override fields.

## CAP-02 — Arm C: fixed verify-and-repair research policy

### Measured problem (on `origin/main`, 2026-09-05)

- `07-first-policy-experiment.md` §3: Arm C "Implementation status: not
  present. The current `enable_verifier` setting adds a supervisor action and
  is a no-op in the fixed graph."
- `src/graph/workflow.py` has exactly two shapes chosen by
  `settings.enable_supervisor`; `verifier_agent` is only a supervisor action.
- 12-p0-work-orders §11 (Puma's W05) must prove "C cannot be represented by
  `ENABLE_VERIFIER=true` under the fixed graph" and needs a structural
  selector to introspect.
- The approved recovery policy (02 §5) requires a failed check to return a
  bounded, named action; today the verifier returns a recommendation string
  that only the supervisor reads.

### Deliverables

1. **Policy selector.** One additive setting
   `research_policy: Literal["legacy", "fixed_verify_repair"] = "legacy"`.
   `legacy` derives the graph from the existing flags exactly as today (arms
   A, B, D stay expressed by `ENABLE_SUPERVISOR` / `ENABLE_EVIDENCE_STORE` /
   `ENABLE_VERIFIER`, untouched). `fixed_verify_repair` requires
   `enable_supervisor=False`, `enable_evidence_store=True`, and
   `enable_verifier=False`; any other combination fails at settings load with
   a message that says why. This is the structural guarantee W05 needs.
2. **Graph shape** `_build_fixed_verify_repair` in `src/graph/workflow.py`,
   dispatched by `_build_graph_shape`; `_build_fixed_pipeline` and
   `_build_supervisor_loop` untouched:

   ```text
   planner -> search -> reader -> synthesizer -> verify
   verify -> (verdict fail and repair_count == 0) -> repair -> re-run the
             affected node(s) -> verify
   verify -> (pass | abstain | repair_count == 1) -> critic -> route_after_critique
   ```

   Node names `verify` and `repair` are new; existing node names unchanged.
3. **Verify node.** Wraps the existing `verifier_agent` (prompt text
   unchanged) and maps its output to a first-class verdict written to new
   additive state keys: `verification_verdict: Literal["pass", "fail",
   "abstain", ""]`, `verification_reason: str`, `repair_count: int`,
   `repair_action: str`. Abstain is the verdict whenever the verifier's
   existing empty/fallback paths fire (no evidence, unparseable output,
   upstream error handled by the gateway) — never coerced to pass or fail.
4. **Typed repair decision, deterministic.** No model call decides the
   repair. `decide_repair(state) -> RepairAction` in a pure module (proposed
   `src/policies/repair.py`):

   | Verifier output | Action | Executes |
   |---|---|---|
   | `missing_evidence` non-empty | `retrieve_missing_evidence` | search with the named gaps as queries -> reader -> synthesizer |
   | `unsupported_claims` non-empty, no missing evidence | `qualify_or_remove_claims` | synthesizer with a bounded repair instruction listing the claims (an additional user-prompt block; system prompt text unchanged) |
   | verdict pass or abstain | `none` | proceeds to critic |

   The remaining approved repairs (re-read named sections, rewrite the named
   section only) are recorded as `not_implemented` reason codes and left for
   a later work order; the decision table is unit-tested row by row.
5. **Bounds.** Exactly one repair per run (`repair_count` cap 1). Every
   repair is followed by re-verification. The critic's revision loop and
   `max_iterations` are unchanged. Cost, cancellation, and timeout enforcement
   already live in the gateway and node wrapper and are not duplicated.
   Repair-triggered search reuses the query refiner's dedup against
   `tried_search_queries` without enabling the refiner.
6. **State.** Add the four keys to `ResearchState` in a **non-total block**
   (a `TypedDict` with `total=False` that `ResearchState` also inherits from),
   with a docstring saying why: the initial-state constructors in
   `src/eval/runner.py` (fenced for Puma's W07) and
   `src/eval/simulate_research.py` (bumblebee's) must keep compiling
   unchanged. Every consumer reads the keys with a default. The constructors
   this lane owns (`src/api/**`, the CLI) may set them explicitly. If an
   existing test enforces constructor totality in a way this breaks, stop
   and report; do not edit either fenced file.
7. **Observability.** Node names appear in traces through the existing
   wrapper; the verdict and repair action are logged as structured fields
   with stable reason codes drawn from `src/errors.py`'s vocabulary where one
   fits, new codes documented otherwise.
8. **ADR** "Fixed verify-and-repair research policy (Arm C)": the selector
   name and values, the node names, the decision table, what W05 may rely
   on, and what is unverified without a live call.
9. **Docs.** `docs/agents/verifier.md` gains the fixed-path verdict mapping;
   new `docs/agents/repair.md`; `docs/architecture.md` gains an additive
   "Three workflow shapes" note; `.env.example` entry.

### Tests (zero-network, fake LLM through the harness)

- Golden: default settings compile to the same node set and edge listing
  as before this change (checked-in listing for both legacy shapes).
- Settings validation: every invalid combination with
  `research_policy=fixed_verify_repair` fails at load.
- Graph shape: the new policy compiles with exactly the nodes and edges in
  §2; `ENABLE_VERIFIER=true` with `research_policy=legacy` and
  `enable_supervisor=False` compiles to the legacy fixed pipeline (no verify
  node) — the W05 impostor case.
- Decision table: one unit test per row, plus the abstain row.
- End-to-end through the compiled graph with canned agent outputs: node
  sequence `... synthesizer, verify, repair, search, reader, synthesizer,
  verify, critic` for a missing-evidence case; `... synthesizer, verify,
  repair, synthesizer, verify, critic` for an unsupported-claim case;
  `... synthesizer, verify, critic` for pass and for abstain; a second
  failure after one repair goes to the critic, never to a second repair.
- Cancellation mid-repair honours the existing cooperative cancel; a cost
  ceiling hit inside verify or repair produces the existing budget-stopped
  outcome, not a crash.
- The scripted research tier's own check (`python -m src.eval.simulate_research`
  then `scripted_tier_check`, per `docs/eval.md`) still passes with default
  settings — run it, do not edit it.
- Existing suites green: `pytest -m "not e2e" -q`, `pytest -m e2e -q`,
  `pytest -m fault -q`, `ruff check .`, `mypy --strict src/`.

### Acceptance

- Arm C is a structural policy: it cannot be produced by any combination of
  the three legacy flags, and the test named above proves it.
- One repair maximum; re-verification always follows a repair; abstain is
  first-class and never becomes pass.
- Default settings are byte-identical in graph shape.
- The ADR publishes the selector, values, and node names for W05.
- The PR body states that verifier and repair *quality* is not verified
  until CAP-06.

### Not in scope

Changing verifier or synthesizer prompt text; the supervisor loop; the
query refiner and reader-recovery flags (held out of the first experiment,
07 §3); section-scoped rewrite; any eval-harness change.

## Wave 1b — CAP-07, authorized 2026-09-05

### CAP-07 — Mock mode reaches every research agent (the keyless path)

Sequencing: starts when the CAP-01 and CAP-02 pull requests are open, and
is rebased onto both, because it edits the same agent files. Its own worker,
its own worktree.

#### Measured problem (assurance lane's frontend survey, 2026-09-05)

- `use_mock_data` is honoured by `src/agents/search.py`, `tutor.py` and
  `assessment.py` and by nothing else. Planner, reader, synthesizer, critic
  and verifier call `call_llm_json`, and `src/llm.py` raises when the key is
  blank. On the seeded stack with no key, `POST /research` returns 202 and
  four seconds later the job is `failed`, `error_type=upstream_model`,
  `llm_calls=0`. There is no path to a briefing without a credential, so
  `docker compose up` cannot demo the product and the scripted research
  tier has to script the model's words (ADR 0075 §"alternatives").
- The failure is mislabelled (the provider was never reached; the credential
  is absent) and `.env.example` ships a non-blank placeholder that passes
  the not-configured guard. Those two are the assurance lane's S-series
  work (ruling R3 on the coordination board), not this order.

#### Deliverables

1. Under `settings.use_mock_data`, each of the five research agents returns
   a deterministic, schema-valid output derived from its inputs, without
   constructing a model client:
   - planner: sub-questions and search queries derived from the query text
     (reuse the existing plan-fallback shape);
   - reader: one analysis per fixture paper built from its abstract, with
     evidence claims when the evidence store is on;
   - synthesizer: a briefing whose citations resolve to the fixture papers
     and whose sections follow the plan, on both the analyses and the
     evidence path;
   - critic: approve at a fixed scripted quality score, no revision;
   - verifier: `verified=true`, no unsupported claims, no missing evidence.
   Output shapes are identical to the live path so the graph, SSE frames,
   export, checkpoints and the eval record layout do not change.
2. The mock briefing carries a visible first line, "Mock mode: fixture
   papers, no model call", mirroring the search agent's fixture banner —
   a mock report must never read as a real one.
3. `src/llm.py` is not touched; the branch lives in each agent, before the
   call, guarded by the same setting the search agent reads.
4. `docs/agents/*.md` for the five agents gain a "Mock mode" line;
   `docs/eval.md`'s "Mock mode is not an LLM stub" paragraphs are the
   assurance lane's to update and are listed for it on the board.
5. ADR: "Mock mode covers the whole research graph".

#### Tests (zero network)

- A new e2e test drives the fixed pipeline under `USE_MOCK_DATA=true` with
  **no** canned agents and reaches a briefing with citations, `$0.0000`,
  `llm_calls=0`, through the real graph; the same through the HTTP surface
  with `ANTHROPIC_API_KEY` blank.
- The spend guard in `tests/conftest.py` is asserted to never fire on the
  mock path (no `_get_client` construction).
- Existing canned-agent e2e tests unchanged and green.
- The scripted research tier is run, not edited: its node-trajectory and
  `$0.0000` assertions must still hold. Its content baseline will move,
  because the words are no longer the harness's; the assurance lane
  regenerates that baseline in its own follow-up PR (board ruling R2).
- Golden: with `use_mock_data=false` every agent's request path is
  byte-identical to before (the CAP-01 golden fixtures cover the gateway;
  add an agent-level assertion that the mock branch is not entered).

#### Acceptance

`docker compose up` with no key produces a visibly-labelled mock briefing
end to end; the eval and e2e harnesses can delete no scripted surface yet
(that is the assurance lane's follow-up) but can run the real nodes at zero
spend; live behaviour is unchanged and proven.

## Wave 2 (not authorized yet)

- **CAP-03** orchestrator-workers for T2: sub-question workers with
  isolated context and an evidence-table merge; depends on CAP-02's verdict
  keys and on Puma's W04 event types for candidate lineage.
- **CAP-04** difficulty features and the deterministic T0/T1 controller;
  depends on CAP-01 (effort as the T0/T1 lever) and CAP-02.
- **CAP-05** SDK 1.x upgrade; lockfile change under ADR 0045's corrected
  procedure; coordinate with both sibling lanes because the lock is shared.
- **CAP-06** funded live smoke; blocked on the owner's funding decision.
- **CAP-07** — promoted to wave 1b on 2026-09-05 (see below); no longer
  optional.

## Shared-file arrangements in force

- `src/config.py` is granted to the assurance lane for one PR (wave D3:
  `api_keys` and `semantic_scholar_api_key` become `SecretStr`, a
  non-additive type change). This lane's additions there live in a marked
  `# ------ Agent capability (CAP-xx)` block; whichever PR merges second
  rebases.
- Before CAP-01 or CAP-02 merges, the coordinator sends the PR number to the
  assurance lane, which runs the scripted research tier against the branch.
  A default-settings trajectory change found there is a CAP bug.
- `src/observability/**` and `src/eval/runner.py` are fenced for Puma's
  W05–W08; this lane does not edit them.

## Worker environment

Each worktree builds its own interpreter: run `make install-dev` once from
the worktree root, which creates `<worktree>/.venv`. Never run `pip`,
`make install*`, or `make clean` against any other directory's venv. The
shared checkout's `.venv` carries an editable install that points at a
deleted worktree from an earlier fleet, which is exactly the failure this
rule prevents. All commands (`ruff`, `mypy`, `pytest`, `python -m src.*`)
run through `<worktree>/.venv/bin/` from the worktree root with
`ANTHROPIC_API_KEY=local-preview-disabled` exported.
