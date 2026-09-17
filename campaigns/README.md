# `campaigns/` — published campaign plans

A **plan artifact** is the design of a campaign, written where a
reviewer can read it in a diff. It is not a campaign: no episode has
run, no provider has been contacted, no dollar is authorized, and
nothing here can authorize one.

## Why this directory exists

`python -m src.campaign` already had two outputs and neither could be
committed. `plan` materializes a campaign under
`outputs/campaign/research-policy-v1/<campaign-id>/`, and `.gitignore`
excludes `outputs/` — correctly, because a campaign directory is a
*run's* record and belongs to the run. `dry-run` prints the whole design
to stdout, which is gone when the shell scrolls.

So the design that
[`docs/agent-engineering/16-w12-approval-packet-draft.md`](../docs/agent-engineering/16-w12-approval-packet-draft.md)
§1 describes — arm A only, 20 cases, 3 repeats, 60 episodes over
`research-policy-v1` — lived as prose in a document, with nothing in the
tree a test could hold it to. This directory is the third output.

**Not under `eval_registry/`.** The registry holds the *authorized*
benchmark objects that `python -m src.contracts.registry parity` counts
(257 today), and a campaign plan is a projection over those objects
rather than one of them. Filing it there would either move the parity
census or need an exception carved into it, and a sibling directory with
a README is cheaper than either.

## What is here

| File | Scope |
|---|---|
| [`w12-arm-a-baseline.plan.json`](w12-arm-a-baseline.plan.json) | 16 §1's funded arm-A baseline: 20 cases × 3 repeats × arm A = 60 episodes, zero caps, no approval |
| [`w12-arm-a-baseline-live.plan.json`](w12-arm-a-baseline-live.plan.json) | The same 60-episode design over the **live** corpus, published beside it because §1's `snapshot` resolves to `USE_MOCK_DATA=true` and would measure nothing. Zero caps, no approval, and not approved — 16 §8.4 puts the two side by side for the owner to choose between |

Each file carries the campaign id, the sealed protocol and registry-lock
digests, the arm declarations and their declaration digest, the case set
in the task set's own order, the repeats, the seed, the corpus mode,
every cap (all zero), `chargeable: false`, `network_calls: 0`, and the
exact command that produced it.

## Regenerating one

Copy the `produced_by` line out of the file and run it from the
repository root:

```
ANTHROPIC_API_KEY=local-preview-disabled \
  python -m src.campaign dry-run --suite research-policy-v1 --arms A \
    --repeats 3 --seed 0 --corpus-mode snapshot \
    --artifact campaigns/w12-arm-a-baseline.plan.json
```

The live variant is the same command with the one argument that
distinguishes it, which is the whole of the difference between them:

```
ANTHROPIC_API_KEY=local-preview-disabled \
  python -m src.campaign dry-run --suite research-policy-v1 --arms A \
    --repeats 3 --seed 0 --corpus-mode live \
    --artifact campaigns/w12-arm-a-baseline-live.plan.json
```

`tests/test_campaign_plan_artifact.py` re-derives the artifact from
`eval_registry/` and compares it with the checked-in file **byte for
byte**, so a registry change that moves a digest fails a test rather
than leaving a document describing a campaign nobody can plan.

## What a plan artifact never contains

- **A positive cap.** `CampaignPlanArtifact` types `chargeable` as
  `Literal[False]` and validates every cap to zero. A chargeable plan is
  not expressible in this schema, which is stronger than a convention
  about what people commit.
- **An approval id.** A zero-cost campaign that claimed one would be
  refused by `CampaignProtocol` before it reached here.
- **`episode_key` or `run_id`.** Both derive from the episode's TaskSpec
  ref, and a `TaskSpec`'s id digests its own `compiled_at` stamp — so
  they move on every plan of the identical protocol against the
  identical registry. The file names both omissions and says why; the
  run ids belong in the campaign directory, which is where a run writes
  them.

## Before anything here is funded

```
python -m src.campaign plan     --arms A --repeats 3
python -m src.campaign rehearse --campaign-id <id>
```

`rehearse` walks the funded path — approval check, ledger open, episode
manifest sealed against the real compiled graph, provider credential,
provider client — under
`ANTHROPIC_API_KEY=local-preview-disabled`, and stops at the first door
a credential opens. It runs no episode, makes no network call, and
leaves the campaign directory exactly as it found it. What it prints is
the list of preconditions still owed, each derived from the tree rather
than transcribed: see `src/campaign/rehearse.py` and 16 §8.
