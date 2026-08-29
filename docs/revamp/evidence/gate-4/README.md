# Gate 4 evidence pack

Assembled by [WO-33](../../06-WORK-ORDERS.md#wo-33--gate-4-evidence-pack-and-residual-risks)
against `origin/main` at **`80f6081`**, which carries every Gate 4 work order
(WO-27 … WO-32, PRs [#109](https://github.com/kudratsingh/arxiv-research-agent/pull/109),
[#114](https://github.com/kudratsingh/arxiv-research-agent/pull/114),
[#115](https://github.com/kudratsingh/arxiv-research-agent/pull/115),
[#116](https://github.com/kudratsingh/arxiv-research-agent/pull/116),
[#117](https://github.com/kudratsingh/arxiv-research-agent/pull/117),
[#118](https://github.com/kudratsingh/arxiv-research-agent/pull/118)) plus the
nightly TBT ruling ([#119](https://github.com/kudratsingh/arxiv-research-agent/pull/119)).

**This pack produces evidence. It fixes nothing.** Where a criterion fails, or
where a claim in a merged document turns out not to match the code, the failure
is reported with the work order that owns it and **no product code, test or CI
file was touched** — the whole diff is this directory. That is WO-33's risk
note, and it is the same rule WO-26 worked under at Gate 3.

**This pack claims no accessibility conformance, and every performance number
in it is a local lab run.** [§5](#5-the-four-claims-this-pack-does-not-make) is
the explicit checklist.

---

## 1. The five criteria

| # | Criterion | Verdict | Where |
|---|---|:-:|---|
| 1 | Every artifact in the [§4.2](../../05-MIGRATION.md#42-gate-4--quality-and-documentation-before-ship) table exists and is non-empty | ✅ **PASS** | [§3](#3-the-42-artifact-table) — 15 of 15 rows resolve |
| 2 | `npm-audit.json` is exact `npm audit --json` output, comparable to the baseline | ✅ **PASS** | [`npm-audit.json`](npm-audit.json) — byte-identical to the command's output; [§4](#4-criterion-2-stated-precisely) |
| 3 | `residual-risks.md` names, **with owners**, field CWV, visual-regression depth, browser matrix limits and the MT-01 dependency | ✅ **PASS** | [`residual-risks.md`](residual-risks.md) — the four are RR-03, RR-01, RR-05, RR-06; **19 entries in total** |
| 4 | The pack makes **none** of the four [§4.3](../../05-MIGRATION.md#43-what-gate-4-must-not-claim) forbidden claims, with a checklist stating each explicitly | ✅ **PASS** | [§5](#5-the-four-claims-this-pack-does-not-make) |
| 5 | Each of the twelve [§11](../../04-ARCHITECTURE.md#11-contract-ambiguities-to-resolve-at-gate-2) ambiguities is listed with the assumption shipped and whether Gate 2 ratified it | ✅ **PASS** | [`contract-ambiguities.md`](contract-ambiguities.md) — 12 of 12, each traced to shipped code and its pinning test |

**All five WO-33 criteria pass. Gate 4 itself does not close**, and this pack is
not the thing that closes it — the coordinator ratifies in
[`DECISIONS.md`](../../DECISIONS.md). Two items stand between here and that
ruling, and neither is WO-33's to resolve:

| Open | Owner | Why it is not this pack's |
|---|---|---|
| **The screen-reader pass has not been executed.** WO-27 criterion 3 is ❌ and the pack says so in its own verdict table. | **WO-27** — the protocol is written and ready | An automated agent on macOS cannot run NVDA and cannot synthesise a VoiceOver transcript. **RR-02** |
| **The TBT runner-ceiling ruling is not yet in `DECISIONS.md`.** PR #119 deliberately did not touch that file, deferring the entry to the Gate 4 close. | **the coordinator** | WO-33 is forbidden from touching STATUS / CHANGELOG / DECISIONS. **RR-10** |

---

## 2. What is in here

| Path | What it is | Produced by |
|---|---|---|
| [`before-after.md`](before-after.md) | **The before/after quality report** D-010 requires — Gate 1 baseline → today, every number re-derived from a committed artifact or a reproduced run, with a third column wherever the honest story needs one. | **WO-33** |
| [`residual-risks.md`](residual-risks.md) | **19 residual risks**, each with owner, status and revisit trigger. RR-01 is WO-28's; RR-02 … RR-19 are WO-33's. | WO-28 + **WO-33** |
| [`contract-ambiguities.md`](contract-ambiguities.md) | The twelve `04` §11 ambiguities: assumption shipped, the module that implements it, the test that pins it, and which kind of ratification it has. | **WO-33** |
| [`rc-03-equivalence.md`](rc-03-equivalence.md) | **The RC-03 legacy-removal equivalence table**, committed into the repository. It existed only in PR #114's body; WO-32 flagged the gap. | WO-31 (verbatim) + **WO-33** |
| [`budget-report.md`](budget-report.md) | `npm run budgets`' own output, verbatim, regenerated on `80f6081`. **All five gated rows pass** against the ceilings WO-31 ratcheted down. | WO-23's script, run by **WO-33** |
| [`coverage-summary.md`](coverage-summary.md) | Measured coverage against WO-31's ratcheted floors. 136 files, 3,080 tests, all four floors met. | **WO-33** |
| [`npm-audit.json`](npm-audit.json) · [`npm-audit-prod.json`](npm-audit-prod.json) | Exact `npm audit --json` (full tree) and `--omit=dev` (production tree, **zero**). | **WO-33** |
| [`a11y-hardening.md`](a11y-hardening.md) | **WO-27's own pack README, verbatim and unedited** — the seven accessibility criteria, the four defects found and fixed, and the eight things it does not claim. See the note at the end of this section. | WO-27 |
| [`axe/`](axe/) | **120 axe reports** — 20 states × light/dark × 320/412/1440 — plus [`summary.tsv`](axe/summary.tsv) and [`README.md`](axe/README.md). **0 violations. Allowlist empty.** | WO-27 |
| [`manual/`](manual/) | [`keyboard.md`](manual/keyboard.md) + 13 raw focus traces; [`reflow/`](manual/reflow/) 18 TSVs; [`reduced-motion.md`](manual/reduced-motion.md) + 4 motion TSVs + 4 forced-colours TSVs; and [`screen-reader.md`](manual/screen-reader.md), **a protocol with every transcription block deliberately empty**. | WO-27 |
| [`lhci/`](lhci/) | The Lighthouse CI gate: [`pass-run/`](lhci/pass-run/) — three profiles, ten cells, three runs each, **80 assertions, all three profiles exit 0** — and [`fail-run/`](lhci/fail-run/), the deliberate-failure proof that the gate can go red. | WO-29 |
| [`ci/csp.md`](ci/csp.md) | The Report-Only sweep, the enforcing header, and the exact eleven-directive policy — captured from a running container, not transcribed. | WO-30's measurement, written up by **WO-33** |
| [`ci/csp-sweep.tsv`](ci/csp-sweep.tsv) | The raw sweep: **20 states × 2 modes = 40 rows, 0 violations, 0 CSP console errors.** Collected from the repository-root `ci/`. | WO-30 |
| [`ci/proxy-log-sample.txt`](ci/proxy-log-sample.txt) | A real, redacted proxy request log — 16 JSON lines, all three outcome shapes, no key, no body, no raw id, no query string. Collected from the repository-root `ci/`. | WO-30 |
| [`ci/web-image.log`](ci/web-image.log) | **C1 green**: the `web image smoke` job's full log — the image builds, boots, serves `/` → 200 and `/api/healthz` → 200, carries the nonce CSP, and its container healthcheck exits 0. | WO-25 + WO-30, collected by **WO-33** |
| [`ci/compose-prod-config.log`](ci/compose-prod-config.log) | **C2 green**: the two `docker build` job steps, plus the same overlay re-rendered locally without `--quiet` so the resolved document is visible. | WO-25, collected by **WO-33** |
| [`ci/audit-gate.log`](ci/audit-gate.log) | `npm run audit:gate`'s own output — production tree 0, dev tree 10 advisories, 10 accounted for by 10 named exceptions. | WO-24's script, run by **WO-33** |
| [`ci/nightly-lighthouse.log`](ci/nightly-lighthouse.log) | **The first green nightly** — run 33265437903, 74 pass / 6 warn / 0 error, all three profiles exit 0, with the per-run spread that shows how little margin the runner leaves. | WO-29's workflow, collected by **WO-33** |

### One file was renamed, and nothing was overwritten

Before this PR, `README.md` in this directory was **WO-27's** pack README —
the accessibility hardening write-up, misfiled at the pack root. WO-33 owns the
index files — [`06` §5.4](../../06-WORK-ORDERS.md#54-fleet-coordination-hazards)
names `docs/revamp/evidence/gate-*/` as owned by WO-26 and WO-33, with
producing work orders writing *into* the pack and *"only WO-26 and WO-33
author the index files"* — so that document was moved to
[`a11y-hardening.md`](a11y-hardening.md) with `git mv` and **not one byte of it
was changed**; every relative link inside it still resolves, because it is in
the same directory. The one inbound link
(`manual/screen-reader.md` → `../README.md`) now lands on this index, which
carries criterion 3's ❌ verdict in [§1](#1-the-five-criteria) — so it still
lands on the page that tells the reader what is outstanding.

---

## 3. The §4.2 artifact table

Criterion 1, row by row. "Non-empty" was checked by size, not by existence
alone; nothing in this pack is a zero-byte placeholder.

| §4.2 artifact | Path | Exists | What it shows |
|---|---|:-:|---|
| Full-matrix axe | [`axe/`](axe/) | ✅ 122 files | 120 reports, 20 states × 2 themes × 3 widths, **0 violations**, allowlist `[]` |
| Keyboard walkthrough | [`manual/keyboard.md`](manual/keyboard.md) | ✅ | 13 scripted walks + 13 raw focus traces, each with observed order **and** restoration |
| Screen-reader logs | [`manual/screen-reader.md`](manual/screen-reader.md) | ✅ | **A protocol, not results.** Three environments, three scenarios, blank blocks. **RR-02** |
| Reflow and zoom | [`manual/reflow/`](manual/reflow/) | ✅ 19 files | 320 CSS px, phone landscape, 200 % and 400 % zoom, and a very long unbroken report |
| Motion | [`manual/reduced-motion.md`](manual/reduced-motion.md) | ✅ | 13 moving elements → 0; 2 status changes over 40 frames; plus the RC-17 forced-colours pass |
| Lighthouse CI | [`lhci/`](lhci/) | ✅ 25 files | 80 assertions, three profiles, all exit 0, with the lab-vs-field caveat restated in §1 and §10 of its README |
| Budgets | [`budget-report.md`](budget-report.md) | ✅ | Final per-route numbers vs. budget; every raised ceiling carries its PR and its reason in `budgets.json`'s `ratchet` array |
| Dependency audit | [`npm-audit.json`](npm-audit.json) | ✅ | Exact `npm audit --json`; [§4](#4-criterion-2-stated-precisely) |
| Web image smoke | [`ci/web-image.log`](ci/web-image.log) | ✅ | C1 green |
| Production overlay | [`ci/compose-prod-config.log`](ci/compose-prod-config.log) | ✅ | C2 green |
| CSP | [`ci/csp.md`](ci/csp.md) | ✅ | Report-Only run with zero violations across the matrix, then the enforcing header, plus the exact policy |
| Proxy observability | [`ci/proxy-log-sample.txt`](ci/proxy-log-sample.txt) | ✅ | A redacted sample proving no key, no body, no raw id — and `web/tests/proxyLogging.test.ts` re-checks it |
| ADRs | [`docs/decisions/0055`](../../../decisions/0055-frontend-architecture-confirmation.md) · [`0056`](../../../decisions/0056-design-tokens.md) | ✅ 8,739 B / 13,655 B | The D-002 confirmation and the design-token contract |
| Docs | [`docs/architecture.md`](../../../architecture.md) · [`testing.md`](../../../testing.md) · [`development.md`](../../../development.md) | ✅ 20,675 B / 19,892 B / 15,532 B | The shell, the data layer, the eight test tiers, the budget gate |
| Residual risk | [`residual-risks.md`](residual-risks.md) | ✅ | 19 entries, each with owner, status and revisit trigger |

Two of these live at the repository root rather than under this directory,
because that is where WO-30 shipped them and where a test reads them from:
`ci/proxy-log-sample.txt` is parsed by `web/tests/proxyLogging.test.ts` at
`ci/…`, and moving it would turn a gate red. **The copies here are collected
duplicates, and the root files remain canonical** — an important distinction if
the two ever disagree, in which case the root file is right and this pack is
stale.

---

## 4. Criterion 2, stated precisely

`npm-audit.json` must be *exact* `npm audit --json` output. It is, and that was
verified rather than assumed: the file `npm run audit:gate` writes was `diff`ed
against a separate, direct `npm audit --json > file` invocation and the two are
**byte-identical** (8,815 bytes each). The gate consumes the audit and writes
the report; it does not reformat it.

Comparability with [`baseline/npm-audit.json`](../../baseline/npm-audit.json) is
therefore structural: both are `auditReportVersion: 2`, both carry the same
three top-level keys, and both can be read by the same parser.

| | Baseline | **Now** |
|---|---|---|
| Dependencies | 669 (prod 119, dev 513) | **1,198** (prod 166, dev 994) |
| Full-tree advisories | 0 | **13** (10 high, 1 moderate, 2 low) across 10 packages / 6 upstream GHSAs |
| **Production-tree advisories** | **0** | **0** — [`npm-audit-prod.json`](npm-audit-prod.json) |

The rise is entirely in the development tree, is entirely accounted for by ten
named exceptions in `web/audit-exceptions.json`, and **seven of the ten arrived
with `@lhci/cli`** — the tool WO-29 added to close a Gate 3 gap. That trade is
named rather than buried: **RR-11**.

---

## 5. The four claims this pack does not make

[§4.3](../../05-MIGRATION.md#43-what-gate-4-must-not-claim) forbids four
claims. Criterion 4 requires a checklist stating each explicitly. This is it.

| # | §4.3 prohibition | This pack's position | Where |
|---|---|---|---|
| **1** | **Not** that Core Web Vitals are met in the field | **Not claimed.** There is no field data. Every performance number in this pack is a single local lab run against a seeded Compose stack on one machine — not a p75, not a percentile, not a median of anything but three consecutive runs of the same script. The lab numbers are **regression guards against the same lab setup** and nothing more. | [`before-after.md` §2](before-after.md) opens with it; [`lhci/README.md` §1](lhci/README.md) and §10; **RR-03** |
| **2** | **Not** WCAG 2.2 AA conformance as a certification | **Not claimed, at any level.** What is claimed is exactly what is measured: 120 axe reports with zero violations, from **one engine, in one browser, on twenty reachable states**; thirteen scripted keyboard walks; sixteen reflow samples; a motion pass; a forced-colours pass in Chromium's two emulated palettes. **The screen-reader pass has not been executed at all.** Nothing here establishes that an announcement is comprehensible, that a focus order makes sense to a person, or that 320 px reflow is *usable* rather than merely non-scrolling. | [`a11y-hardening.md` §4](a11y-hardening.md#4-what-this-pack-does-not-claim) — eight numbered limits; [`gate-3/known-gaps.md` §9](../gate-3/known-gaps.md#9-what-this-pack-does-not-claim); **RR-02**, **RR-05** |
| **3** | **Not** that multi-tenancy exists | **Not claimed.** There is no user identity of any kind. Everyone who reaches the product is the same principal, sees the same threads, and can delete any of them. What shipped is **seams and nothing more** — S1 `resolveUpstreamPrincipal`, S2 the reserved `/api/auth/*` path with **no files created**, S5 the reserved navigation slot. A specific misreading is pre-empted: the Caddy HTTP basic auth at `deploy/hetzner/Caddyfile` is a **deployment gate, not a user account** (S7), and the UI must never render it as a signed-in user. | [`04` §10](../../04-ARCHITECTURE.md#10-identity-ready-seams-for-mt-01); [D-009](../../DECISIONS.md); **RR-06**, **RR-13** |
| **4** | **Not** that the frozen contract's ambiguities are resolved | **Not claimed.** All twelve remain frontend *assumptions*. Four were ratified as named D-010 rulings and eight as part of the approved architecture package; **none was answered by the backend and none changed the contract.** Items 7 (partial-report export) and 12 (web healthcheck semantics) — the two §11 singled out as needing an explicit human answer — were answered **under the D-010 delegation**, which is a coordinator ruling, not an upstream resolution. | [`contract-ambiguities.md`](contract-ambiguities.md) — all twelve, with the kind of ratification each has |

Two further non-claims this pack volunteers, because they are the ones a reader
is most likely to assume:

- **No before/after delta against the `lhci` corpus.** `@lhci/cli` pins
  Lighthouse 12.6.1; the baseline and both Gate 3 corpora are 13.4.1. A delta
  across a major version is a delta against a moving scoring curve.
  [`lhci/README.md` §7](lhci/README.md); **RR-09**.
- **Not that the nightly gate has margin.** It is green — run
  [33265437903](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33265437903),
  74 pass / 6 warn / 0 error, [`ci/nightly-lighthouse.log`](ci/nightly-lighthouse.log)
  — but on that same run the plan-review mobile cell's worst TBT sample was
  **302 ms against a 300 ms error ceiling**, passing only on its median, and a
  landing LCP sample came in at 2,578 ms against 2,500. The runner's variance
  is the dominant term. [`before-after.md` §7](before-after.md); **RR-10**.

---

## 6. The cost boundary

**No paid model call was made at any point in producing this pack, and no
Compose stack was started.**

[`06` §0](../../06-WORK-ORDERS.md#0-conventions) states the rule: *"No work
order calls a paid model. `POST /research` against a real key is never exercised
by any automated tier."*

WO-33 needed less than its predecessors did. The three measurements reproduced
here — the route budgets, the dependency audit and the coverage run — need no
backend at all, and `docker compose config` validates a file and starts nothing.
Everything else is read out of corpora committed by WO-27, WO-29, WO-30 and the
Gate 3 pack, or downloaded from a CI run's log. The commands are in
[`before-after.md` §8](before-after.md).

---

## 7. Findings this pack did not fix

WO-33 fixes nothing, so each of these is reported with its owner. **None
changes a criterion verdict**; all five criteria pass with these standing.

| # | Finding | Owner |
|---|---|---|
| 1 | **`budget-report.md` states something false, on every run.** The baseline-reproduction note reads *"The retained baseline was captured from source commit `e6e8739`, which is not an ancestor of this repository's history"*. It **is** an ancestor: `git merge-base --is-ancestor e6e8739 HEAD` returns 0 and `git ls-tree e6e8739` succeeds. The sentence is generated text in `web/scripts/route-budgets.mjs:661`, so it reappears in every report — including [this pack's](budget-report.md). The **conclusion** it supports (that a 1-byte residue on `/` is a tree difference, not a measurement error) may well still hold; the premise given for it does not. | **WO-23** (`route-budgets.mjs`) |
| 2 | **`05-MIGRATION.md` §4.2 misattributes the enforcing CSP header.** It says "the enforcing header in `next.config.mjs`". The document-route policy is minted per request by `web/middleware.ts`; `next.config.mjs` carries only the *inert* policy for the three excluded paths. [`ci/csp.md` §1](ci/csp.md) documents what actually ships and does not repeat the error. | **WO-30** / whoever edits `05-MIGRATION.md` |
| 3 | **Two stale line references.** `05-MIGRATION.md` §3.1 cites `.github/workflows/ci.yml:150-154` for the base Compose check, which is now lines 171–175; `04-ARCHITECTURE.md` §11 item 2 cites `web/lib/useResearchStream.ts:59-66`, a file **WO-31 deleted**. Both are Gate 1/Gate 2 artifacts that this pack does not edit. | the document owners |
| 4 | **The Gate 4 budget measurements sit slightly above WO-31's ratchet figures** — `emitted-css` 9,604 B vs 9,507 B (+97) and `/c/[id]` 182,814 B vs 182,776 B (+38), both beyond the "under 10 B" oscillation `budgets.json` documents. **Not drift: merge order.** WO-27's accessibility CSS landed *after* WO-31's ratchet (`577b4c5` after `cf61462`). Every ceiling still holds. Reported so a reader comparing this pack with PR #114's body finds the explanation here rather than a discrepancy. | none — recorded, not a defect |
| 5 | **`last-event-id`'s reservation is ruled but unpinned.** D-010 ruling 15 declares the allowlist entry reserved; no test is named for it and no comment marks it. A future client setting the header, or a reader deleting the entry, would take nothing red. | **WO-30** / the proxy owner — **RR-14** |
| 6 | **Two broken relative links, both WO-27's and both pre-existing on `origin/main`.** [`a11y-hardening.md`](a11y-hardening.md) §2 points at `web/.storybook/storyRail.ts` three levels up where it needs four; [`manual/reduced-motion.md`](manual/reduced-motion.md) links `keyboard.md#7-diagnostics` where the heading anchor is `#7-diagnostics-disclosure`. Neither was caused by this pack's rename — the first was broken at the same path depth before it. Both are left unfixed: WO-33 fixes nothing, and this pack's claim is that WO-27's document is byte-identical. A link checker run over all fifteen markdown files in the pack finds **those two and no others: 384 links and anchors checked, 382 resolve.** | **WO-27** |

---

## 8. How to read this pack

Start with [`before-after.md`](before-after.md) for what changed and by how
much, then [`residual-risks.md`](residual-risks.md) for what did not. Those two
are the pack. Everything else is the evidence they cite.

If you have time for one more file, make it
[`gate-3/known-gaps.md`](../gate-3/known-gaps.md): it is the list Gate 3 wrote
of what it had *not* established, and this pack is largely the record of
closing it — with three items that did not close and one that got bigger:

| `known-gaps.md` §0 item | Now |
|---|---|
| 1 — manual keyboard **and screen-reader** passes | **Half closed.** Keyboard done (13 walks); **screen reader not executed** — **RR-02** |
| 2 — visual-regression baselines do not exist | Closed for `darwin`; **inert on the CI runner** — **RR-01**, **RR-07** |
| 3 — CSP is not enforced | **Closed** — enforcing, [`ci/csp.md`](ci/csp.md) |
| 4 — Lighthouse is not wired to a nightly | **Closed** — `nightly.yml`, though no nightly has yet passed (**RR-10**) |
| 5 — two budgets raised | **Reversed** — six ceilings ratcheted *down*, [`before-after.md` §3.2](before-after.md) |
| 6 — three dependency advisories accepted | **Grew to ten** — **RR-11** |
| 8 — five Storybook coverage rows missing | Closed by [#108](https://github.com/kudratsingh/arxiv-research-agent/pull/108), verified in the [Gate 3 addendum](../gate-3/ADDENDUM.md) |
| 9 — one flaky e2e assertion | **Closed** by WO-27 (the assertion now reads time, not a count); a *different* load sensitivity is **RR-17** |
| 10 — the pinned theme-hydration flash | **Unchanged** — **RR-18** |
| 11 — WO-20's two unwired edges | **Unchanged** — **RR-19** |
| 13 — three mobile §8.2 budgets breached | Closed by [#111](https://github.com/kudratsingh/arxiv-research-agent/pull/111), verified in the addendum |
| 14 — six story play functions | **Closed** by WO-27 |
