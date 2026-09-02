# Phase W flags — the inventory, and the count discrepancy

Gate W1's flag row reads:

> **Flags: all four default-off; flag-off behaviour identical** | full-suite
> runs both positions | W01–W07, indexed by W19

This file resolves that row and records where its wording does not match the
merged tree.

---

## 1. The inventory

Read out of `src/config.py` on `3ccb650` (`grep -n "enable_" src/config.py`,
plus its five comment-fenced Phase W sections, at lines 456, 870, 931, 950 and
977). Phase W added **four capability flags**, and they are all
`default=False`:

| # | Setting | Env | Declared by | Mounts | Off-position behaviour |
|---|---|---|---|---|---|
| 1 | `enable_learner_profile` | `ENABLE_LEARNER_PROFILE` | **WO-W02** (ADR 0058); **WO-W07** shares the gate | `GET/PUT/DELETE /learn/profile` **and** `GET /learn/progress` | routes exist, answer `404 learner_profile_disabled` |
| 2 | `enable_learn_content` | `ENABLE_LEARN_CONTENT` | **WO-W15** | `GET /learn/paths`, `GET /learn/paths/{path_id}` | routes exist, answer `404 learn_content_disabled` |
| 3 | `enable_session_loop` | `ENABLE_SESSION_LOOP` | **WO-W03** (ADR 0057/0059) | `POST/GET /learn/sessions`, learner-turn resume | routes exist, answer `404 session_loop_disabled` |
| 4 | `enable_assessment_judge` | `ENABLE_ASSESSMENT_JUDGE` | **WO-W04** (ADR 0060) | the one-shot explain-back judge inside a session | the informal `recorded_ungraded` close is preserved |

**Four is the right number, and the row's arithmetic is right by accident.**
Seven Phase W cards touched behaviour that a reader would expect to sit behind
its own flag; four flags exist. The other three deliberately ship without one,
and each is a decision recorded in the tree rather than an omission:

| Card | Why it has no flag of its own | Where that is stated |
|---|---|---|
| **WO-W01** — job kinds, `awaiting_learner` | ships the *lifecycle* only. It adds two settings (`session_turn_timeout_sec`, `session_max_turns`) and no capability. | `src/config.py:456-465`, verbatim (lines 462-465): *"No flag lives here: WO-W01 ships the lifecycle only, and the capability flags (`enable_session_loop` and the rest of the Phase W ladder) land with the graph that needs them."* |
| **WO-W05** — bounded Tier-1 session memory | is a component of the session graph; it has no surface of its own to mount. Its only settings are the ones the graph already carries. | PR [#143](https://github.com/kudratsingh/arxiv-research-agent/pull/143) body; ADR 0061 |
| **WO-W07** — the append-only progress ledger | *shares* WO-W02's flag by design, so that one switch mounts the whole learner surface rather than half of it. Its own setting is `progress_event_store`. | `src/config.py:931-936` and `enable_learner_profile`'s own description: *"WO-W07 shares this gate."* |

**WO-W06** — the per-session cost cap — likewise adds no flag: it adds
`learning_session_max_cost_usd` (default `0.50`) and
`learning_session_cost_cap_behavior` (default `refuse`), which are ceilings,
not switches. See [`cost-reconciliation.md`](cost-reconciliation.md).

### The discrepancy the coordinator should see

**The four flags are not independent.** [§0's standing constraint](../../05-WEDGE-WORK-ORDERS.md#0-conventions)
says *"every capability lands behind an **independent** default-off flag in
`src/config.py`"*. Three of the four are in a **ladder**, enforced by three
`model_validator`s that raise at settings load rather than per request:

```
enable_assessment_judge  →  enable_session_loop  →  enable_learner_profile  →  enable_api_auth
                                     ↘  enable_checkpointing
```

- `_check_learner_profile_requires_auth` (`src/config.py:906-929`) — the
  profile is keyed on a principal, so it refuses `enable_api_auth=false`.
- `_check_session_loop_dependencies` (`src/config.py:996-1013`) — the session
  loop refuses without the profile *and* without checkpointing; the judge
  refuses without the session loop.

Only `enable_learn_content` is genuinely independent. This is not a defect —
each edge is argued in the field description and in ADR 0058 — but "four
independent flags" is not what shipped, and the consequence is the largest
single item in [`known-gaps.md`](known-gaps.md): **the zero-config auth-off
`docker compose up` demo cannot run a guided session at all.**

### One more thing the row does not say

`docker-compose.yml:103` sets `ENABLE_LEARN_CONTENT: ${ENABLE_LEARN_CONTENT:-true}`.
The *setting's* default is `False` in `src/config.py`; the **demo stack turns
it on**, deliberately, and says why in its own comment (lines 96-102): the only
path it can publish is the labeled-fixture one, whose banner says so in every
response, and `deploy/hetzner/compose.prod.yml` sets it back to false. So
"default-off" is true of the code and not true of the container a reader
actually starts. Recorded here rather than filed as a defect.

---

## 2. Flag-off behaviour identical — where each proof lives

Every one of these runs in ordinary `pytest -m "not e2e"`, which is CI's
`pytest (unit + integration)` job. Counts are `--collect-only` on `3ccb650`
with the repo venv.

| Flag | Off-position proof | On-position proof |
|---|---|---|
| `enable_learner_profile` | `tests/test_learn_profile_routes.py::TestTheFlagIsARealOffSwitch` — `test_every_verb_is_404_while_the_flag_is_off`, `test_nothing_is_written_while_the_flag_is_off`, **`test_existing_endpoints_are_untouched_while_the_flag_is_off`** (the "identical" half); `TestTheFlagPairing::test_the_flag_is_off_by_default` | the rest of `tests/test_learn_profile_routes.py` (**30 tests** in the file) |
| `enable_learner_profile`, via WO-W07 | `tests/test_progress_events.py::TestProgressEndpoint::test_flag_off_leaves_no_surface`, and `test_the_ledger_cannot_be_enabled_without_auth` | `tests/test_progress_events.py` (**76 tests**) |
| `enable_learn_content` | `tests/test_api_learn_routes.py::TestFlagGating::test_routes_exist_and_report_the_flag_honestly`, `test_the_flag_is_off_by_default` | `tests/test_api_learn_routes.py` (**18 tests**) |
| `enable_session_loop` | `tests/test_guided_session_graph.py::TestSessionApiEndToEnd::test_owner_scope_and_flag_off_are_real` (asserts `detail == "session_loop_disabled"`, line 276); `test_session_flag_requires_profile_and_checkpointing` (line 388) pins **both** ladder edges | `tests/test_guided_session_graph.py` (**7 tests**), `tests/test_api_session_lifecycle.py` (**26 tests**) |
| `enable_assessment_judge` | `tests/test_assessment_judge.py::TestGraphIntegration::test_flag_off_preserves_informal_recorded_ungraded_close` (line 239) — the exact "behaviour identical" claim; `test_assessment_flag_is_default_off_and_requires_session_loop` (line 324) | `tests/test_assessment_judge.py` (**15 tests**) |

Two structural proofs sit beside them:

- **The contract does not move with the flag.** `tests/test_contract_openapi_snapshot.py:111` records the rule in its own comment — the published schema does not change on a flag flip; the route answers `404 learner_profile_disabled` while it is off.
- **The whole suite runs at the defaults.** CI's `pytest -m "not e2e" -q` runs
  with no Phase W flag set, i.e. all four off, and reports **2090 passed** on
  `3ccb650` (run
  [33630982183](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33630982183),
  job *pytest (unit + integration)*). The flag-on positions are reached inside
  the suite by constructing `Settings` with the flag set, not by a second
  full-suite run — so the row's *"full-suite runs both positions"* is satisfied
  **per test**, not by two whole-suite invocations. Stated plainly because the
  wording invites the stronger reading. The **coordinator state-probe of main
  `3ccb650`, 2026-09-02** ran the same selection outside CI and read **2038
  passed, 52 skipped** — the same suite at all-flags-off, minus the 52 that
  need CI's Postgres.
