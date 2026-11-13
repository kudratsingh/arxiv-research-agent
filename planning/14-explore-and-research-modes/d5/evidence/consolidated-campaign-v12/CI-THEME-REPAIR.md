# CI theme race: reproduced and repaired

Run [43361922306](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/43361922306)
at publication5ca260e9 failed the fixture browser suite: the document reported
preference dark while its painted theme was light. The remaining browser tiers
were skipped by that failed step; they are not claimed green.

Hydration initially renders the server snapshot, system. Its effect used that
captured value to resolve the OS setting even when the pre-paint script or user
had already chosen dark. An already queued OS callback had the same problem.
The shared control now checks the current document preference before writing.

Two deterministic regressions fail before the guard and pass after. The stored
preference test now also asserts the resolved theme; a new test invokes the old
queued listener immediately after a manual choice. The existing browser test
for stored dark hydration is now a required pass, with all assertions retained.
No timeout, production request, evidence, floor or budget changed.

Local results after the repair:

- Theme unit tests19/19; complete frontend221files,4281pass/9skip in87.82s.
- Coverage98.16%statements,94.37%branches,94.14%functions,99.52%lines.
- Fixture reading-loop browser suite8/8 desktop/mobile,17.4s, including axe.
- Production theme browser suite12/12 desktop/mobile,8.1s, including the
  deliberate pre-hydration click. Both saved light and dark and system behavior
  pass. Production build, unchanged route budgets, lint and typecheck pass.
- The dev-server-only harness passed10/12 but its two intentional chunk-hold
  tests stalled waiting for DOMContentLoaded. The exact same assertions pass
  against the production build. An initial local harness typing mistake and
  an occupied3127 port were corrected in disposable verification configuration;
  no unrelated process was stopped and no owner data used.

The failed CI trace, all harness failures, logs and screenshots are retained at
`~/Machine-Learning-Projects/arxiv-evidence/d5-campaign-20261112/ci/`.
Final Python coverage and exact-head remote CI are recorded separately.

The sealed qualification application remains587492d5. This frontend-only fix is
published as a separate compatibility commit: every sealed producer hash,
model/schema/source/settings binding and packet byte remains identical. See
[the fresh binding proof](SEALED-PRODUCER-AFTER-THEME-REPAIR.json). No new packet
or historical rebind is needed; no owner approval has been recorded.

## Pre-paint listener follow-up

Compatibility commit7fa3de0c also fixes the independent pre-paint OS listener.
Running the shipped script with a system start, a manual dark choice and an OS
change reproduced another overwrite (19pass/1fail). The listener now writes the
initial preference before resolving it, and future OS events check the live
preference. [Binding and verification receipt](PREPAINT-LISTENER-REPAIR.json).

Final frontend coverage run:221files,4291pass/no skips in121.56s;
98.18%statements,94.01%branches,94.14%functions,99.50%lines. Nine existing
build-dependent checks now execute because production assets are available.
The event-synchronized production browser suite passes14/14 desktop/mobile in
9.7s. Lint, typecheck, production build and unchanged route budgets pass.
Original failure logs and previous successful evidence remain retained.
The qualification application and packet are unchanged.
