# ADR 0102: live-evaluation analysis and protocol sealing

Date: 2026-09-18  
Status: accepted for LE-C

## Context

The first live-evaluation ledger requires a report that preserves query
difficulty, repeated episodes, and null judge scores. The campaign protocol
also contains runtime settings whose changes alter the experiment even when
the task registry is unchanged.

## Decision

Campaign reports will retain scored observations by query, arm, and metric;
null scores remain unscored with their reason. Intervals resample queries first
and repeats within each selected query using a recorded seed. A pooled Wilson
row is retained for descriptive context and is labelled “pooled, assumes
independence — not for gating”.

The protocol digest freezes the settings in document 07 §4, including model,
temperature, structured-output, reader, thinking/effort, iteration, paper,
result, and cost settings. A changed value creates a new campaign id. Planner
caps count the three judge rubrics, and measured per-role token quantiles plus
revision counts re-derive the estimate under the packet’s 1.25x rule.

## Consequences

Variance reports can show between-query difficulty instead of hiding it in a
pooled mean, while small samples carry an explicit caveat. Every plan digest
and campaign id moves when the frozen settings are introduced; existing plan
artifacts must therefore be regenerated. Prices remain estimates until the
owner re-verifies them immediately before credentials are supplied.
