# Agent design pages

One page per agent in `src/agents/`. Every page follows the same
skeleton — **Purpose · Flow · Inputs · Outputs · Prompt design ·
Failure modes · Flags · Testing · Related** — with agent-specific
sections (evidence path, recovery path, dedup, iteration cap …)
inserted wherever they read best.

These pages describe `main` as it is. Workflow-level wiring — the two
graph shapes, checkpointing, the API layer — lives in
[`docs/architecture.md`](../architecture.md).

| Agent | Runs under | Gated by | Page |
|---|---|---|---|
| Planner | both shapes | always on | [planner.md](planner.md) |
| Search | both shapes | always on | [search.md](search.md) |
| Reader | both shapes | always on | [reader.md](reader.md) |
| Synthesizer | both shapes | always on | [synthesizer.md](synthesizer.md) |
| Critic | both shapes | always on | [critic.md](critic.md) |
| Supervisor | supervisor loop | `enable_supervisor` | [supervisor.md](supervisor.md) |
| Verifier | supervisor loop | `enable_verifier` | [verifier.md](verifier.md) |
| Query refiner | supervisor loop | `enable_query_refiner` | [query_refiner.md](query_refiner.md) |
| Tutor | guided-read session graph | `enable_session_loop` | [tutor.md](tutor.md) |

## The two shapes

```mermaid
flowchart LR
  subgraph fixed["Fixed pipeline — enable_supervisor off (default)"]
    direction LR
    P["planner"] --> S["search"] --> R["reader"] --> Y["synthesizer"] --> C["critic"]
    C -->|"revision_target"| P
    C --> FIN(["END"])
  end
  subgraph loop["Supervisor loop — enable_supervisor on"]
    direction LR
    SUP{"supervisor"} --> ACT["planner · search · reader<br/>synthesizer · critic<br/>verifier · query_refiner"]
    ACT --> SUP
    SUP -->|"stop"| FIN2(["END"])
  end
```

In the fixed pipeline the critic's `revision_target` drives the only
conditional edge, and it can point at `planner`, `search`, or
`synthesizer`. In the supervisor loop every action node edges straight
back to the supervisor, which picks the next action or stops. The
verifier and query refiner exist only in the loop, and only when their
own flags are on.

## Cross-cutting flags

Each page's **Flags** section lists what drives that agent. The ones
that touch more than one:

- `enable_evidence_store` — reader emits `EvidenceClaim`s, synthesizer
  writes from them, verifier judges against them. All three switch
  together (ADRs 0016 / 0017).
- `enable_prompt_isolation` — reader-side wrapping and output
  sanitizing; the choke point that protects the supervisor's routing
  (ADR 0020). Extended to the planner's `prior_context` by ADR 0033.
- `enable_prompt_caching`, `<agent>_model` — per-agent LLM plumbing,
  uniform across all seven LLM-calling agents (ADRs 0022 / 0021). The
  search agent makes no LLM call and reads neither.
- `max_cost_usd` — checked by the supervisor before its own LLM call,
  and independently by the API runner between nodes under both shapes
  (ADRs 0033 / 0051).
