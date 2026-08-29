# axe rerun — row-for-row diff against the retained baseline

Produced by [WO-26](../../06-WORK-ORDERS.md#wo-26--gate-3-evidence-pack),
criterion 6. Raw reports: [`axe/`](axe/). Baseline:
[`../../baseline/axe/`](../../baseline/README.md).

**This file claims no accessibility conformance.** See
[`known-gaps.md` §9](known-gaps.md#9-what-this-pack-does-not-claim).

---

## 1. Headline

| | Retained Gate 1 baseline | This rerun |
|---|---:|---:|
| Reports | 12 | **40** |
| Reports with at least one violation | 12 | **0** |
| Total violations | 36 | **0** |
| Total violating nodes | 77 | **0** |
| Distinct rules violated | 6 | **0** |
| Allowlist entries | n/a | **0** |

All six rules the gate holds at zero are breached somewhere in the baseline, so
none of them is a rule the baseline merely failed to exercise.

## 2. How the two corpora are made comparable

| | Baseline | This rerun |
|---|---|---|
| Engine | axe-core 4.13.0 | axe-core 4.13.0 (asserted `^4.13.` per report) |
| Tag set | `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`, `best-practice` | identical — verified equal in all 40 reports |
| Browser | local Google Chrome 151 | Playwright chromium |
| Viewport | 1440 × 1200 | 1440 × 1200 (`AUDIT_VIEWPORT`) |
| Stack | seeded local Compose stack, `ANTHROPIC_API_KEY=local-preview-disabled` | the same, on an isolated Compose project |
| Naming | `<state>.json` | `<state>.<theme>.json` |

The `@axe` tag is pinned to the chromium project deliberately: the twelve
retained reports were taken in Chrome, and a Firefox or WebKit
`color-contrast` measurement is a *different* measurement, not a stricter one.

D-012 ruling 6 is why the viewport is pinned rather than left to Playwright's
default: at 1280 × 720 axe downgrades below-the-fold contrast findings from
`violations` to `incomplete`, so a narrower window would have reported *fewer*
violations than the baseline and made this comparison flattering rather than
comparable.

## 3. The allowlist is empty

`web/e2e/axe-allowlist.json` is three bytes:

```json
[]
```

The harness holds it there with four assertions of its own: it refuses an entry
with no written justification, refuses any entry that would suppress one of the
six gated rules, refuses a malformed document, and asserts emptiness directly.

`PENDING_COMPOSITION` — the register WO-22 used to pin nine residual violations
in files WO-20 was about to replace — is **also empty**. WO-20 deleted all nine
pins (D-012 ruling 3). It was never an allowlist and never suppressed anything;
its test fails when a pinned defect stops being observable.

## 4. Row-for-row diff — the twelve pairs

The mapping is `BASELINE_COUNTERPART` in `web/e2e/axe.spec.ts`, rewritten into
[`axe/baseline-map.tsv`](axe/baseline-map.tsv) on every run.

| Baseline report | §4 | Baseline violations (rule × nodes) | Live report | Live | Δ nodes |
|---|---|---|---|:-:|---:|
| `home.json` | 1 | 2 rules / 4 nodes — `landmark-one-main` × 1, `region` × 3 | `landing.light.json` | **0** | −4 |
| `conversation-empty.json` | 5+B | 2 rules / 4 nodes — `landmark-one-main` × 1, `region` × 3 | `thread-empty.light.json` | **0** | −4 |
| `conversation-populated.json` | 7 | 2 rules / 5 nodes — `landmark-one-main` × 1, `region` × 4 | `thread-populated.light.json` | **0** | −5 |
| `conversation-populated-dark.json` | 7 | 2 rules / 5 nodes — `landmark-one-main` × 1, `region` × 4 | `thread-populated.dark.json` | **0** | −5 |
| `plan-review.json` | 9 | 5 rules / 11 nodes — `aria-allowed-role` × 1, `color-contrast` × 3, `landmark-one-main` × 1, `listitem` × 1, `region` × 5 | `plan-review.light.json` | **0** | −11 |
| `running.json` | 10 | 3 rules / 7 nodes — `color-contrast` × 1, `landmark-one-main` × 1, `region` × 5 | `running.light.json` | **0** | −7 |
| `failed-partial.json` | 14 | 5 rules / 12 nodes — `aria-allowed-role` × 1, `color-contrast` × 2, `landmark-one-main` × 1, `listitem` × 1, `region` × 7 | `failed-partial.light.json` | **0** | −12 |
| `cancelled.json` | 13 | 5 rules / 12 nodes — `aria-allowed-role` × 1, `color-contrast` × 3, `landmark-one-main` × 1, `listitem` × 1, `region` × 6 | `cancelled.light.json` | **0** | −12 |
| `expired-job.json` | 16 | 3 rules / 7 nodes — `color-contrast` × 1, `landmark-one-main` × 1, `region` × 5 | `expired.light.json` | **0** | −7 |
| `backend-offline.json` | 4+F | 2 rules / 4 nodes — `landmark-one-main` × 1, `region` × 3 | `rail-error-upstream.light.json` | **0** | −4 |
| `conversation-not-found.json` | 21 | 3 rules / 3 nodes — `landmark-one-main` × 1, `page-has-heading-one` × 1, `region` × 1 | `thread-not-found-inline.light.json` | **0** | −3 |
| `framework-not-found.json` | 22 | 2 rules / 3 nodes — `landmark-one-main` × 1, `region` × 2 | `route-not-found.light.json` | **0** | −3 |
| **Total** | | **36 violations / 77 nodes** | | **0** | **−77** |

### The six gated rules, per rule

| Rule | Baseline reports affected | Baseline nodes | Live nodes | Verdict |
|---|---:|---:|---:|---|
| `landmark-one-main` | 12 of 12 | 12 | **0** | ✅ zero |
| `region` | 12 of 12 | 48 | **0** | ✅ zero |
| `color-contrast` | 5 of 12 | 10 | **0** | ✅ zero |
| `listitem` | 3 of 12 | 3 | **0** | ✅ zero |
| `aria-allowed-role` | 3 of 12 | 3 | **0** | ✅ zero |
| `page-has-heading-one` | 1 of 12 | 1 | **0** | ✅ zero |

The baseline's four confirmed cross-state problems are all discharged: the
shell now has a `<main>` in every audited state, content is inside landmarks,
the event-log semantics that produced `aria-allowed-role` / `listitem` are gone
with `EventLog.tsx` leaving the render path, the muted status/error
combinations meet contrast, and the inline thread-not-found state has an `h1`.

## 5. The twenty-eight reports with no baseline counterpart

The gate audits **20 §4 states × 2 themes = 40** reports. Twelve pair with a
baseline report; the other 28 are new coverage — states the Gate 1 baseline
never captured, plus the dark half of every state.

All 28 report **0 violations**. The complete per-state table, with the contrast
pass counts, is [`axe/summary.tsv`](axe/summary.tsv). States the baseline had
no equivalent for at all:

`rail-loading` (2+6) · `rail-empty` (3) · `rail-error-proxy-503` (F) ·
`failed-no-result` (15+23) · `submission-error-500` (17) ·
`rate-limited-429` (18) · `unauthorized-401` (19) · `validation-422` (20) ·
`attached-status-unknown` (C)

## 6. Incomplete results

Across all 40 reports there is exactly **one** `incomplete` entry — a single
`color-contrast` item on `plan-review.dark.json`. The baseline carried an
`incomplete` in nine of its twelve reports (eight `color-contrast`, one
`bypass`).

`incomplete` is axe declining to decide, not a violation: it is what the engine
returns when it cannot resolve a background — a gradient, a partially
transparent stack, or text over an image. It is reported rather than suppressed,
and it is why the gate counts violations and incompletes in separate columns.

## 7. The real-render contrast proof

WO-22 criterion 4 required the three replacement colour pairs from
[`03` §3.1](../../03-DESIGN-BRIEF.md#31-how-the-ratios-were-produced) to be
confirmed **in a real render**, not arithmetically.
[`axe/contrast-proof.tsv`](axe/contrast-proof.tsv):

| Pair | fg | bg | Documented | Measured | Size | Source |
|---|---|---|---:|---:|---|---|
| light `ink-muted` / `sunken` | `#4a636b` | `#e7eef0` | 5.44 | **5.43** | 12px | token probe only — no composed surface uses it yet |
| light `ink-muted` / `surface` | `#4a636b` | `#ffffff` | 6.39 | **6.38** | 12px | product surface (3 nodes, e.g. `.ew-shell__workspace`) |
| light `review-text` / `surface` | `#8c5610` | `#ffffff` | 6.08 | **6.08** | 12px | token probe only — no composed surface uses it yet |

The 0.01 gaps are rounding between the brief's published ratio and axe's own
computation; every pair clears the 4.5:1 AA floor with room to spare.

**Two of the three are honest about being probes.** `ink-muted` on `sunken` and
`review-text` on `surface` are measured on an injected probe node because no
composed surface currently paints that combination. The harness says so in the
artifact rather than implying a product surface it cannot point at — and the
one pair that *does* appear in the product names the three nodes it was
measured on.

## 8. What this proves, and what it does not

**Proved.** Forty renders — twenty states in two themes, in Chrome at
1440 × 1200, on a seeded stack — produce zero violations of the tag set the
baseline used, with an empty allowlist and nothing suppressed. Every one of the
77 violating nodes the baseline recorded is gone, and the twelve pairs are
directly comparable rule for rule.

**Not proved.** Everything automation cannot reach: keyboard order, focus
restoration, announcement quality, reflow *usability*, screen-reader
comprehension. Also not covered here: the other two widths (320 and 412) and
forced-colors — WO-27 criterion 1 owns the full matrix of state × theme ×
width, and RC-17's forced-colors pass. axe checks rules; it does not check
whether the product is usable by someone who depends on those rules being met.
