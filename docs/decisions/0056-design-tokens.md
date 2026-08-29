# 0056. Design tokens: one source of values, one source of names, and a ratcheted budget gate

- **Status**: accepted
- **Date**: 2026-08-29
- **Deciders**: EXEC coordinator under the D-010 delegation
  (`docs/revamp/DECISIONS.md` D-010 rulings 11 and 16 ratify RC-01 and the
  RC-01…RC-21 reconciliations)

## Context

The pre-revamp `web/` had literal colours scattered across components, dark mode
by `prefers-color-scheme` alone — no user control, no persistence, no
`color-scheme` declaration — and **no bundle budget of any kind**. Three
problems follow from that, and they are the reason this ADR exists:

1. A renamed or re-valued colour meant a grep across every component.
2. A contrast regression was invisible until someone ran axe by hand. The
   retained baseline had failing `color-contrast` audits.
3. Nothing stopped a route's JavaScript from growing. "It feels fine locally"
   was the entire performance gate.

Phase 2 of the revamp authored the values
([`design/tokens.json`](../revamp/design/tokens.json)); Phase 3 authored the
mechanism ([`04-ARCHITECTURE.md` §6](../revamp/04-ARCHITECTURE.md)). The two
were written concurrently on separate branches and **disagreed about the role
set** — §6.1 fixed a placeholder list so the brief could be written against
something, and the brief then shipped a different one. RC-02 reconciled that;
RC-01 reconciled the budget table against the three self-hosted typefaces the
brief introduced. Both reconciliations were ratified at Gate 2.

## Decision

### 1. The token contract — four hops, two enforcement mechanisms

Values flow one way, and each hop has exactly one job:

| Hop | File | Job |
|---|---|---|
| 1 | [`docs/revamp/design/tokens.json`](../revamp/design/tokens.json) | Source of truth. Carries the values *and* the evidence — 56 recorded contrast checks, and 3 baseline axe regressions mapped to the token that fixes each. |
| 2 | `web/app/tokens.css` | **The only file in `web/` that may contain a literal colour.** Declares every custom property and both theme mechanisms. |
| 3 | `web/lib/tokens.ts` | The single source of *names*. Contains no literal values — every entry is a `var(--…)` reference, and it exports the union types. |
| 4 | `web/tailwind.config.ts` | Builds `colors`, `spacing`, `borderRadius`, `boxShadow`, `fontFamily`, `fontSize`, `transitionDuration` and `transitionTimingFunction` **from `lib/tokens.ts`**, so a utility class and a custom property can never disagree. |

There is deliberately **no generator script**. The chain is hand-maintained and
held by two gates instead:

- **A parity test.** `web/tests/tokens.test.ts` asserts bidirectional parity
  across `tokens.json`, `tokens.css` and `tokens.ts` in *both* themes — an
  orphan in either direction fails, so a token cannot be added to one file and
  forgotten in another. It also recomputes the contrast ratios rather than
  trusting the recorded ones.
- **An ESLint rule.** Literal hex/rgb/hsl colours are rejected in `app/` and
  `components/`, with `tokens.css` the only exemption. Since WO-31 removed the
  last legacy allow-list entry, the rule applies with **no exemption of any
  kind** beyond that one file.

`web/e2e/axe.spec.ts` reads `tokens.json` directly and re-checks the pairs in a
real browser, because a computed ratio and a rendered one are not the same claim.

Theme selection supports all three states: `:root` (light), both
`@media (prefers-color-scheme: dark)` and `:root[data-theme="dark"]`, and
`:root[data-theme="light"]` so an explicit light choice beats a dark system.
Tailwind's `darkMode` is `["class", '[data-theme="dark"]']` to match.

**Tailwind stays on 3.x.** Tailwind 4 is a separate ADR — see
ADR [0055](0055-frontend-architecture-confirmation.md) constraint 3.

### 2. The reconciled role set (RC-02)

**The brief's role set wins; `04-ARCHITECTURE.md` §6.1's enumeration is
superseded.** §6.1 was a placeholder written to unblock a concurrent branch, and
§6 says so twice ("the brief owns the values"). What survives from §6.1 is the
*namespacing convention* and the whole of the §6.2 mechanism above.

The shipped set:

| Namespace | Count | Notes |
|---|---|---|
| `--color-*` | **23 roles**, identical key sets in light and dark | `canvas surface sunken ink ink-muted ink-faint ink-disabled border-subtle border-strong primary primary-strong primary-on focus signature signature-text signature-on review review-text review-surface critical critical-text critical-surface critical-on` |
| `--space-*` | 13 steps + 10 layout constants | 4px unit |
| `--size-*` | 12 | Touch targets, control heights, focus-ring geometry |
| `--radius-*` | 5 | Nothing above 6px except `radius-dot`, reserved for the trace spine's checkpoint marks |
| `--elevation-*` | 4 per theme (`elev-0`…`elev-3`) | **New** — §6.1 had no namespace for it |
| `--font-*` | 3 families: `ui`, `report`, `mono` | All SIL OFL 1.1 |
| `--text-*` | 13 steps | Three parallel ramps (`ui-*`, `report-*`, `mono-*`) plus `display` |
| `--duration-*` | 5 | The union of both sources: `instant fast base slow ambient` |
| `--ease-*` | 3 | `standard enter exit` |

Four differences from §6.1 are deliberate and load-bearing:

- **`success` and `warning` do not exist.** "A second accent colour for
  'success'. Cut." — the brief's appendix. `StatusBanner`'s warning severity maps
  onto an existing role (RC-17).
- `sunken` replaces `raised`; `border-subtle`/`border-strong` replace `rule`;
  `primary-on` replaces `primary-ink`; a `signature` family replaces `accent`.
- `--elevation-*` is added.
- The space scale is px-valued rather than the abstract `0 1 2 3 4 6 8 12 16 24`.

**Status is never conveyed by colour alone.** Each of the 8 status roles carries
a distinct colour, a distinct mark *shape*, and a distinct word.

Five of the 56 recorded contrast checks are recorded **failures with a rule
attached**, not defects — e.g. `review` on `surface` is 3.42, which is why
`review` is a non-text mark only (it passes 3:1) and text uses `review-text`.
Recording the forbidden pair beside the permitted one is what stops the next
person re-deriving it wrongly.

### 3. The ratified budgets (RC-01) and the ratchet rule

Font files are woff2 binaries emitted as static assets; they never appear in a
route's JS chunk union, so they can neither consume nor be hidden by the JS
headroom. The budgets are therefore **per-asset-class ceilings, not one
page-weight number** — which is what made the brief's and the architecture's
tables consistent once read correctly. RC-01 added the missing figure the brief
was reaching for as a derived, reported-not-gated row.

Measurement is gzip at zlib level 6, summed per file, polyfills excluded from
every JavaScript row; fonts are counted as raw woff2 bytes because woff2 is
already Brotli-compressed, so file size *is* wire weight.

**The live ceilings, from `web/budgets.json`:**

| Row | Ceiling | | Gate |
|---|---:|---|---|
| `/` first-load JS | 166,912 B | 163 KiB | every PR |
| `/c/[id]` first-load JS | 192,512 B | 188 KiB | every PR |
| Shared framework/runtime chunk | 139,264 B | 136 KiB | every PR |
| All emitted CSS | 11,264 B | 11 KiB | every PR |
| All self-hosted fonts (woff2, latin subset) | 109,568 B | 107 KiB | every PR |
| Total transferred JS on a settled report route | 245,760 B | 240 KiB | per-PR chromium E2E (external) |
| *Derived:* total first-load transfer for `/c/[id]`, cold cache | 313,344 B | 306 KiB | reported, **not** gated |

**The ratchet rule.** A ceiling may only move in a PR that edits
`web/budgets.json` **in the same commit** and states the reason in the PR body.
There is no escape hatch, and that is enforced rather than asserted:
`web/scripts/route-budgets.mjs` accepts no command-line arguments and reads no
environment variable, it errors on any argv, and `web/tests/budgets.test.ts`
asserts those properties against the script's own source text so they cannot
regress. The report is written *before* the script exits non-zero, so a breach
uploads the evidence of its own breach.

**Ratchet history.** Every movement is recorded inside `budgets.json`'s
`ratchet` array and printed by every budget report:

| # | Row | From → To | Why |
|---|---|---|---|
| 1 | Shared framework/runtime | 122,880 → 141,312 B | **D-011 ruling 1** (PR #77). Measured 130,865 B on untouched `main`: React DOM plus the Next app-router runtime exceed the inferred ceiling *before any application code*. 138 KiB gave 8.0% headroom, matching the other rows. |
| 2 | `/` first-load JS | 148,480 → 167,936 B | **D-012 ruling 4** (PR #101). Measured 158,899 B. The in-budget alternative was built and measured, not assumed — a `React.lazy` composer landed `/` at 143,426 B, but Next resolved the lazy fallback into the prerendered HTML, so the route would have shipped a document with no `h1` and failed `page-has-heading-one`. **Accessibility gate beats budget row.** |
| 3 | Six rows, downward | see below | **WO-31** (PR #114), same ratchet rule, ceilings re-seeded to the measured post-cleanup values. |

WO-31's ratchet-down, old → new, each measured on the rebased branch:

| Row | From → To | Measured | Headroom kept |
|---|---|---:|---:|
| `/` | 167,936 → 166,912 | 158,878 | +5.1% |
| `/c/[id]` | 199,680 → 192,512 | 182,776 | +5.3% |
| Shared framework/runtime | 141,312 → 139,264 | 131,641 | +5.8% |
| Emitted CSS | 12,288 → 11,264 | 9,507 | +18.5% |
| Self-hosted fonts | 122,880 → 109,568 | 103,476 | +5.9% |
| Derived total first-load | 334,848 → 313,344 | 295,759 | +5.9% |

Two things about that ratchet are worth keeping:

- **The deletions shipped almost no bytes, and that is the finding rather than a
  disappointment.** WO-31 removed twelve dead modules and nine test files; across
  the PR `/` moved 158,899 → 158,839 B (−60) and `/c/[id]` 182,784 → 182,723 B
  (−61). The legacy components were already un-composed by WO-20 and already
  tree-shaken — what WO-31 removed was dead *files*, not shipped weight.
- **`total-transferred-js` is the one row that cannot be ratcheted**, because its
  `enforcedBy` names a Playwright transfer assertion that was never written, so
  there is no measurement to ratchet *to*. `web/tests/budgets.test.ts` asserts
  that too, rather than leaving the omission to be read as an oversight.

No ceiling is set at a hairline over its measurement: repeated builds of an
unchanged tree oscillate by under 10 B on the three JS rows, because content
hashes inside the webpack runtime manifest are themselves a few bytes of
differing gzip input.

## Alternatives considered

- **Generate `tokens.css` and `tokens.ts` from `tokens.json` at build time** —
  the obvious choice, and rejected for this repo's size. A generator is another
  build step, another thing to run in CI, and another failure mode; the parity
  test gives the same guarantee (no file can drift from another) at a fraction of
  the moving parts, and it fails with a better message. Revisit if the token set
  outgrows hand-maintenance.
- **Tailwind's own theme as the single source of truth** — would put values in a
  config file that CSS cannot read, so anything outside a utility class (the
  pre-paint theme script, raw CSS, SVG) would need a second copy.
- **CSS-in-JS with a typed theme object** — solves naming, but ships a runtime
  and moves colour values into the JS bundle, against the budgets this same ADR
  ratifies.
- **A budget as a reported metric rather than a gate** — this is what the
  baseline effectively had, and it is why there was no budget at all. A number
  nobody's PR can go red against does not constrain anything.
- **Setting ceilings aspirationally below the measurement** — rejected in favour
  of seeding at the measured value plus headroom and ratcheting down. A threshold
  nobody can meet is a threshold that gets skipped.

## Consequences

- **Positive**: renaming or re-valuing a role touches two files and no
  components. Contrast is checked twice — computed in a unit test and rendered in
  a browser — so a regression is a red job rather than a discovery. Themes work
  from a user control, a system preference, or neither. Every route's weight is a
  gate, and every ceiling movement carries its measurement and its reason in the
  file itself, so the history is readable without `git log`.
- **Negative**: the four-hop chain is hand-maintained, so adding a token means
  editing three files (and the parity test will tell you which one you missed).
  The budget gate can block a PR for a legitimate feature, and the escape is
  deliberately social — measure, then justify the raise in the PR body — rather
  than a flag. The derived total-transfer row is reported and not gated, so page
  weight can grow within the per-class ceilings without anything going red.
- **Follow-ups**:
  - `total-transferred-js` has no measurement behind it. Either write the
    Playwright transfer assertion its `enforcedBy` names, or drop the row.
  - `docs/revamp/design/tokens.json`'s `$meta.status` still reads
    `"proposed; not yet implemented in web/"`. It is fully implemented; the field
    is stale.
  - The Vitest dual-project function-list concatenation hazard keeps the
    coverage `functions` floor artificially low; de-duplication is queued with the
    config owner.
  - The performance half of the budget story now runs nightly rather than
    per-PR (`.github/workflows/nightly.yml`, WO-29), so a regression in a
    Core Web Vital is caught within a day instead of at the gate. Whether
    any of it should move into the per-PR job is an open question, and a
    cost one.
