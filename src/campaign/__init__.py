"""Campaign orchestration: lock, matrix, resume, denominators, approval.

P0-WO07. A no-cost-capable layer *around* the existing evaluation runner,
never inside it: `src/eval/runner.py` behaves exactly as it always has
when no campaign is given, and this package writes to its own output root
(`outputs/campaign/research-policy-v1/<campaign-id>/`). The rollback is
therefore "stop using the campaign CLI", not a revert.

What it owns, and why each piece exists:

- `arms` — the five conceptual selectors from 07 §4 mapped onto real
  settings, with arm E declared `capability_missing` and refused as
  runnable rather than approximated by the nearest flag combination.
- `manifest` — the sealed campaign record, with the campaign id *derived*
  from the protocol, the registry lock and the lineage, so raising a cap
  cannot resume the old campaign.
- `matrix` — the whole `cases x repeats x arms` design, interleaved
  within each block from a seed the manifest records, with every
  identity (`replicate_group_id`, `episode_key`, `run_id`) derived rather
  than assigned.
- `ledger` — the expected-denominator ledger, written before any episode
  runs, in which a failure, a timeout, a cancellation, a budget stop and
  a null metric all stay counted.
- `approval` — a local, file-backed approval-record backend satisfying
  W03's admission interface, so a metered provider can be admitted in a
  test. Real approval records stay external and a live campaign still
  needs the owner's D9 approval.
- `episode` — sealing one episode's `RunManifest` with the campaign's
  real lock ref, registry resolution, budgets and approval.
- `planner` / `cli` — `plan`, `dry-run`, `resume`, `status`.
- `summary` — the three cost categories and the statistics, delegated to
  `src/eval/stats.py`.

See [ADR 0082](../../docs/decisions/0082-campaign-lock-and-denominators.md).
"""

from __future__ import annotations

from src.campaign.errors import CampaignError

__all__ = ["CampaignError"]
