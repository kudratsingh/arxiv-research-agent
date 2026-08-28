# WO-02 — typography, self-hosted fonts, and CLS proof

Produced by [WO-02](../../06-WORK-ORDERS.md#wo-02--typography-self-hosted-fonts-and-cls-proof).
Captured 2026-08-28 on macOS 15 (darwin 25.5.0), Google Chrome 151.0.7922.174,
Lighthouse 13.4.1, Node 22.23.2.

Everything here is regenerable:

```bash
cd web && node scripts/measure-fonts.mjs          # byte table + metrics
cd web && node scripts/measure-fonts.mjs --json   # the same, machine-readable
```

The subsetting pipeline is a one-off and is written out in full in
[§2](#2-how-the-faces-were-built) rather than committed as a script, because
it runs against a throwaway Python environment and produces artefacts that
are themselves committed.

---

## 1. Criteria at a glance

| # | Criterion | Status | Where |
|---|---|---|---|
| 1 | Three families self-hosted, latin subset, `font-display: swap`, OFL 1.1 committed, no external host | **Met** | [§2](#2-how-the-faces-were-built), [§3](#3-per-face-byte-table) |
| 2 | `size-adjust` / `ascent-override` / `descent-override` measured per family, method recorded | **Met** | [§4](#4-measured-fallback-metrics) |
| 3 | Lighthouse CLS = 0.000 on `/` and `/c/[id]` with fonts swapping | **Met** | [§5](#5-lighthouse-cls) |
| 4 | Per-face byte table (gzip and raw) totalled against the ratified budget | **Met, budget holds** — 103,476 B of 122,880 B, no ratchet needed | [§3](#3-per-face-byte-table) |
| 5 | Literata Italic 400 included per RC-20 | **Met** — included, not synthesised | [§3](#3-per-face-byte-table) |
| 6 | A test asserts the three `--font-*` variables resolve and no component names a family | **Met** | `web/tests/fonts.test.ts` |

**The headline for WO-23 and RC-01: the font budget holds.** RC-01 warned
that eight faces at 15.0 KiB each made the 120 KiB ceiling *less* likely to
hold and named a mitigation ladder. The first rung of that ladder — variable
woff2 with a restricted weight axis — was enough on its own. All eight
logical faces ship in five files totalling **103,476 B**, which is 84.2% of
the ratified 122,880 B with **19,404 B of headroom**. No budget raise is
requested and `budgets.json` needs no ratchet on the font row.

---

## 2. How the faces were built

### 2.1 Sources

Official release artefacts from the [google/fonts](https://github.com/google/fonts)
repository, pinned to commit `ade3d1533e06b2b1462ffcde8e08b129627ca360`.
Each file was fetched from `raw.githubusercontent.com` at that commit and
checksummed on arrival:

| Upstream path | Bytes | SHA-256 |
|---|---:|---|
| `ofl/atkinsonhyperlegiblenext/AtkinsonHyperlegibleNext[wght].ttf` | 114,552 | `5a455d1cfa099b601ab70751bb9673e8fe1854dc4500c80e1a220d0d75e31745` |
| `ofl/literata/Literata[opsz,wght].ttf` | 955,132 | `b41138c9373112f32abb589cc22e8674b06ed4048b0c513be922bdd26f274440` |
| `ofl/literata/Literata-Italic[opsz,wght].ttf` | 902,728 | `d483dfaeba9cbf4ce71d32a52ee65df82f7e35b15fff8d1011cdb242d1fcd465` |
| `ofl/ibmplexmono/IBMPlexMono-Regular.ttf` | 135,580 | `6a3412f058c7d8dfd9170c41e85ade48e5156ecb89356110ca57a0a27734af46` |
| `ofl/ibmplexmono/IBMPlexMono-Medium.ttf` | 136,704 | `a9b4c49bb299e05b5f6c481e7fb5e78943d2793249a0c8874ab574a2d1ea6755` |

The matching `OFL.txt` from each family directory is committed unmodified
beside the fonts as `web/app/fonts/OFL-*.txt`. All three families are SIL
Open Font License 1.1. Name IDs 13 and 14 (licence and licence URL) are
retained in every subset, so each shipped file also carries its licence
internally.

### 2.2 Toolchain

A throwaway virtualenv, not committed:

```bash
python3 -m venv /tmp/wo02-fonts/venv          # Python 3.13.7
/tmp/wo02-fonts/venv/bin/pip install "fonttools==4.60.1" "brotli==1.1.0"
```

### 2.3 Commands

`$SRC` is the directory of downloaded upstream TTFs, `$DEST` is
`web/app/fonts`, and `$PY` is the venv's Python.

```bash
LATIN='U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2190-2193,U+2212,U+2215,U+FEFF,U+FFFD'
FEATURES='calt,ccmp,clig,curs,dnom,frac,kern,liga,locl,mark,mkmk,numr,rclt,rlig,rvrn'

sub () {   # sub <input.ttf> <output.woff2>
  "$PY" -m fontTools.subset "$1" \
    --unicodes="$LATIN" \
    --layout-features="$FEATURES" \
    --name-IDs+=13,14 \
    --flavor=woff2 \
    --output-file="$2"
}

# UI: keep the weight axis, clipped to the 400-700 the design uses.
"$PY" -m fontTools.varLib.instancer "$SRC/AtkinsonHyperlegibleNext[wght].ttf" \
  wght=400:700 -o /tmp/atk.ttf
sub /tmp/atk.ttf "$DEST/AtkinsonHyperlegibleNext-400-700.woff2"

# Report: pin optical size to the report body size, keep wght 400-600.
"$PY" -m fontTools.varLib.instancer "$SRC/Literata[opsz,wght].ttf" \
  opsz=17 wght=400:600 -o /tmp/literata.ttf
sub /tmp/literata.ttf "$DEST/Literata-400-600.woff2"

# Report italic (RC-20): only weight 400 is used, so pin both axes.
"$PY" -m fontTools.varLib.instancer "$SRC/Literata-Italic[opsz,wght].ttf" \
  opsz=17 wght=400 -o /tmp/literata-italic.ttf
sub /tmp/literata-italic.ttf "$DEST/Literata-Italic-400.woff2"

# Mono: IBM Plex Mono has no upstream variable font, so 400 and 500 are static.
sub "$SRC/IBMPlexMono-Regular.ttf" "$DEST/IBMPlexMono-400.woff2"
sub "$SRC/IBMPlexMono-Medium.ttf"  "$DEST/IBMPlexMono-500.woff2"
```

Output checksums, so a re-run can be compared byte for byte:

| File | SHA-256 |
|---|---|
| `AtkinsonHyperlegibleNext-400-700.woff2` | `29a3a8275e99a5ed415cbeaa9602f430cc3354e5badc0c64f2ee2a6c3c672edc` |
| `IBMPlexMono-400.woff2` | `8c3ef34970f7fde16cb4cc36c0f68d94d680e84af6bad6fcb27d57faeedc6cae` |
| `IBMPlexMono-500.woff2` | `14e10411a8b8bc9f71466d4853a2bb159a50ca4ec38d5aa7412e5b0b2f67e220` |
| `Literata-400-600.woff2` | `589db8696776c9b42c9154a4cca1faf16c1b9f262f12130836cf99534c1a55f0` |
| `Literata-Italic-400.woff2` | `b4548e0bfb359ab9c501361f6fbbb3793ab2ecc2df4ce305710034e6d6388b66` |

### 2.4 Two decisions in the subset, stated

**The unicode range is the Google Fonts `latin` subset plus two arrows.**
The stock `latin` range carries `↑` (U+2191) and `↓` (U+2193) but not `←`
(U+2190) or `→` (U+2192), and the product already emits `→` in user-visible
strings (`web/lib/useResearchStream.ts`). Rather than let one glyph fall out
of the family mid-sentence, the range was widened from `U+2191,U+2193` to
`U+2190-2193`. Cost, measured: **+264 B** across all five files.

**Literata's optical-size axis is pinned at 17, not kept live.** Keeping
`opsz` variable across the 15-34px band Literata is actually set at costs
**+17,592 B** — measured, not estimated: the roman goes from 34,416 B to
51,928 B, which takes the family total to 120,724 B, or 98.2% of the whole
budget. That buys optical compensation at the thread title (22px) and
landing prompt (34px) only; the report body at 17px, which is the
overwhelming majority of Literata on screen, is exactly on the pinned value
either way. The 19,404 B of headroom is worth more to the work orders that
follow than the compensation is here. If a later work order wants the axis
back, this is the number it costs.

---

## 3. Per-face byte table

Generated by `node web/scripts/measure-fonts.mjs`.

| File | Faces it serves | Raw (B) | gzip (B) |
|---|---|---:|---:|
| `AtkinsonHyperlegibleNext-400-700.woff2` | UI 400, 600, 700 | 19,892 | 19,920 |
| `Literata-400-600.woff2` | Report 400, 600 | 34,416 | 34,407 |
| `Literata-Italic-400.woff2` | Report italic 400 (RC-20) | 20,896 | 20,920 |
| `IBMPlexMono-400.woff2` | Mono 400 | 13,996 | 14,019 |
| `IBMPlexMono-500.woff2` | Mono 500 | 14,276 | 14,299 |
| **Total** | **8 logical faces in 5 files** | **103,476** | **103,565** |
| Budget (RC-01, ratified D-010) | | 122,880 | — |
| **Headroom** | | **+19,404** | — |

**gzip is larger than raw, and that is the correct result.** woff2 is
already Brotli-compressed; gzipping it again adds framing and gains nothing.
The number that matters for the budget and for transfer is the **raw**
column — a server must not re-compress these, and Next.js does not. The gzip
column is reported because criterion 4 asks for it, not because anything
should ship that way.

RC-01 sized the risk at eight faces × 15.0 KiB and expected a squeeze. The
actual per-file cost is lower because two of the three families ship as one
variable file each rather than as three and two static instances:

| Strategy | Files | Raw total | Verdict |
|---|---:|---:|---|
| Static instances, 8 files, hinted | 8 | 125,344 | **over** by 2,464 B |
| Static instances, 8 files, unhinted | 8 | 115,936 | under, but drops hinting |
| **Variable axes, 5 files, hinted — the shipped configuration** | **5** | **103,132** | **under by 19,748 B** |
| Variable axes, 5 files, unhinted | 5 | 93,628 | under, but drops hinting |

All four rows were measured on the stock Google `latin` range so they are
comparable to each other. The shipped files add the two arrows from §2.4,
which is why the committed total is 103,476 B rather than 103,132 B.

The shipped configuration keeps TrueType hinting, which the unhinted rows
give up for another ~9.5 KB. Since the budget holds with hinting, there was
no reason to spend the rendering quality. The static-instance rows are what
RC-01 sized the risk against: eight separate faces would have breached the
ceiling unless hinting were dropped, exactly as predicted.

### Related budget rows this PR moves

| Row | Budget | Before | After | Note |
|---|---:|---:|---:|---|
| All self-hosted font files | 122,880 B | 0 | **103,476 B** | new row, first occupant |
| All emitted CSS (gzip) | 12,288 B | 4,288 B | **6,040 B** | +1,752 B: five `@font-face` rules from `next/font/local`, three metric-adjusted fallback faces |

Route JavaScript is unchanged: `next/font/local` emits CSS and static
assets, not JS.

---

## 4. Measured fallback metrics

**No value in `web/app/fonts/fallback.css` was chosen. Every one is
measured, and the measurement is re-runnable and self-checking.**

### 4.1 Method

`web/scripts/measure-fonts.mjs` drives headless Chrome over the DevTools
protocol. The harness page inlines each committed woff2 as a `data:` URL,
loads it through the FontFace API, and lays out one reference string twice —
once in the webfont, once in the fallback — reading three numbers each time:

- **width** — advance width of the reference string, from
  `CanvasRenderingContext2D.measureText`.
- **baselineFromTop** — distance from the top of a `line-height: normal`
  line box to the alphabetic baseline, read off a zero-height
  `vertical-align: baseline` marker span.
- **lineBoxHeight** — height of that same line box.

Every face this work order ships has `hhea.lineGap = 0`. That is not
assumed: the script parses the committed woff2 files directly (its own WOFF2
table-directory reader, Brotli via `node:zlib`) and fails the run if any
face has leading. With no leading to distribute, the line box is exactly
ascent + descent and the baseline sits exactly at ascent, so the two DOM
numbers give ascent and descent directly:

| File | unitsPerEm | hhea ascender | hhea descender | hhea lineGap |
|---|---:|---:|---:|---:|
| `AtkinsonHyperlegibleNext-400-700.woff2` | 1000 | 984 | −316 | **0** |
| `Literata-400-600.woff2` | 1000 | 1177 | −308 | **0** |
| `Literata-Italic-400.woff2` | 1000 | 1177 | −308 | **0** |
| `IBMPlexMono-400.woff2` | 1000 | 1025 | −275 | **0** |
| `IBMPlexMono-500.woff2` | 1000 | 1025 | −275 | **0** |

The descriptors then follow the definitions in CSS Fonts 5 — `size-adjust`
scales the em, and the ascent/descent overrides are percentages of that
already-scaled em, so each is divided by the size adjustment:

```
size-adjust       = webfont.width / anchor.width
ascent-override   = (baselineFromTop / 100px)                  / size-adjust
descent-override  = ((lineBoxHeight - baselineFromTop) / 100px) / size-adjust
line-gap-override = 0%
```

Measured at 100px so a sub-pixel error in the ratio surfaces as a readable
number of pixels.

The reference string is the product's own landing and disclosure copy
([03 §1.4](../../03-DESIGN-BRIEF.md#14-landing-copy)), so the ratio is
weighted by the letter distribution of the text this product actually sets:

> What should the literature settle? Generating a plan starts a billable
> run. You review and edit the plan before any arXiv search or paper reading
> happens.

### 4.2 What "against the declared fallback stack" had to mean

The criterion asks for measurement against the declared fallback stack. That
stack cannot be measured against *directly*, and the reason is worth stating
because it changes the numbers.

CSS cannot hang `size-adjust` on a generic family. There is no way to write
"make `system-ui` 4% narrower"; the descriptors only exist on an
`@font-face`, and an `@font-face` needs concrete fonts in its `src`. So the
adjusted face has to name real fonts through `local()`, and the ratio has to
be taken against whichever of those the platform supplies — not against the
generic the declared stack nominally prefers.

The declared stacks are measured anyway, and reported below, because they
answer a different and useful question: what the swap would have cost with
no adjusted face at all.

Only `size-adjust` is affected. Ascent and descent come from the webfont
alone and are exact on every platform.

### 4.3 The numbers

Measured in Google Chrome 151.0.7922.174 on macOS, at 100px.

| Family | Adjustment anchor | `size-adjust` | `ascent-override` | `descent-override` | `line-gap-override` |
|---|---|---:|---:|---:|---:|
| Atkinson Hyperlegible Next | `local("Arial")` | 99.24% | 98.75% | 32.24% | 0% |
| Literata | `local("Georgia")` | 106.74% | 110.55% | 29.04% | 0% |
| IBM Plex Mono | `local("Menlo-Regular")` | 99.66% | 102.35% | 27.09% | 0% |

These are exactly the values in `web/app/fonts/fallback.css`.

### 4.4 Verification: the adjusted faces, re-measured

The script does not stop at computing the descriptors. It declares the
adjusted `@font-face` for real, lays the reference string out in it, and
reports the residual against the webfont. A residual near zero is the
evidence that the swap cannot move anything.

| Family | Residual width | Residual baseline | Residual line box | Unadjusted width | Unadjusted line box |
|---|---:|---:|---:|---:|---:|
| Atkinson Hyperlegible Next | −0.14 px (−0.002%) | **0.00 px** | **0.00 px** | −7.08% | −12.00 px |
| Literata | −0.06 px (−0.001%) | **0.00 px** | **0.00 px** | −6.32% | −35.00 px |
| IBM Plex Mono | −0.87 px (−0.009%) | **0.00 px** | **0.00 px** | +0.34% | −12.00 px |

Baseline and line box are exactly identical; width is within 0.01% over a
~7,000 px reference string. The last two columns are the counterfactual: with
no adjusted face, the same swap would have moved text by up to 7.08%
horizontally and jumped the line box by up to 35 px at 100px type. That is
the CLS this section exists to remove.

**This verification pass caught a real defect before it shipped.** The first
run measured a −0.33% residual on the mono family. The cause: `local()`
matches PostScript and full names, not family names, so `local("Menlo")`
silently misses on macOS and the src list fell through to Courier New — a
different font with different metrics than the one the adjustment was
computed against. The fix was `local("Menlo-Regular")`, and the script now
probes every candidate through a real `local()` `@font-face` rather than
through a family name, because the two are not equivalent.

### 4.5 Cross-platform spread

The anchors were chosen for consistency across platforms, not just for this
machine. Prose advance width at 100px; `size-adjust here` is the descriptor
each candidate would have produced.

| Family | Font | Role | Resolved here | Prose width (px) | size-adjust here |
|---|---|---|---|---:|---:|
| Atkinson | *(declared generic stack)* | no adjusted face | — | 6219.82 | 107.62% |
| Atkinson | `Arial` **(anchor)** | src | yes | 6744.92 | 99.24% |
| Atkinson | `Helvetica Neue` | src | yes | 6766.20 | 98.93% |
| Atkinson | `Helvetica` | src | yes | 6744.92 | 99.24% |
| Atkinson | `Liberation Sans`, `DejaVu Sans` | src | no | — | — |
| Atkinson | `SF Pro Text`, `SF Pro`, `.SFNS-Regular`, `.AppleSystemUIFont`, `Segoe UI` | probe | **no** | — | — |
| Literata | *(declared generic stack)* | no adjusted face | — | 6717.58 | 106.74% |
| Literata | `Georgia` **(anchor)** | src | yes | 6717.58 | 106.74% |
| Literata | `Times New Roman` | src | yes | 6084.86 | 117.84% |
| Literata | `Liberation Serif`, `DejaVu Serif` | src | no | — | — |
| IBM Plex Mono | *(declared generic stack)* | no adjusted face | — | 9271.58 | 99.66% |
| IBM Plex Mono | `Menlo-Regular` **(anchor)** | src | yes | 9271.58 | 99.66% |
| IBM Plex Mono | `Courier New` | src | yes | 9241.50 | 99.98% |
| IBM Plex Mono | `Consolas`, `DejaVu Sans Mono`, `Liberation Mono` | src | no | — | — |
| IBM Plex Mono | `Menlo`, `SFMono-Regular`, `SF Mono`, `.SFNSMono-Regular` | probe | **no** | — | — |

Reading of that table, per family:

- **UI.** Arial heads the list because it is the one sans present on macOS,
  Windows and — as the metric clone Liberation Sans — most Linux images, so
  a single 99.24% holds across all three. The declared stack's own first
  choice is `system-ui`; none of its macOS spellings can be named in
  `local()` at all, which is why the naive 107.62% is not the number to use.
- **Report.** Georgia is what the declared serif stack resolves to on both
  macOS and Windows, so on those platforms the adjusted face and the plain
  fallback are the same font and the adjustment is exact. Times New Roman is
  deliberately last: at 117.84% it is the worst of the four to anchor on.
- **Mono.** Menlo is what the declared mono stack resolves to on macOS.
  Courier New precedes Consolas on purpose — IBM Plex Mono's advance is
  0.6em and Courier New's is 0.6em, where Consolas' is 0.55em, so on Windows
  the plainer face is the metrically honest swap.

**The honest limitation:** `size-adjust` is exact on a platform that
supplies the anchor and approximate on one that does not. A Linux image with
neither Arial nor Liberation Sans, or without Georgia, will carry a residual
this run cannot quantify. Ascent and descent, which drive the larger of the
two unadjusted errors (up to 35 px of line box), are exact everywhere.

### 4.6 Recorded back into the design tokens

`design/tokens.json` `typography.loading.fallbackMetrics` previously read
"must be MEASURED … No invented values are recorded here." It now records
the measured values under `fallbackMetricsMeasured`, with the method and a
pointer back to this file.

---

## 5. Lighthouse CLS

Local seeded stack, brought up exactly as the Gate 1 baseline did — with
`ANTHROPIC_API_KEY=local-preview-disabled` and
`docs/revamp/baseline/fixtures/seed-local-baseline.sh`. `POST /research` was
never called and no real key exists anywhere in this run.

### 5.1 Results

| Route | State | Form factor | Throttling | **CLS** | Shift elements | LCP | Perf | Evidence |
|---|---|---|---|---:|---:|---:|---:|---|
| `/` | landing | mobile | simulate | **0.000** | 0 | 1,534 ms | 100 | [JSON](lighthouse/home-mobile.json) |
| `/` | landing | desktop | simulate | **0.000** | 0 | 364 ms | 100 | [JSON](lighthouse/home-desktop.json) |
| `/c/[id]` | populated report | mobile | simulate | **0.000** | 0 | 2,885 ms | 95 | [JSON](lighthouse/conversation-populated-mobile.json) |
| `/c/[id]` | populated report | desktop | simulate | **0.000** | 0 | 625 ms | 100 | [JSON](lighthouse/conversation-populated-desktop.json) |
| `/` | landing | mobile | **devtools** | **0.000** | 0 | 1,613 ms | 99 | [JSON](lighthouse/home-mobile-fontswap.json) |
| `/c/[id]` | populated report | mobile | **devtools** | **0.000** | 0 | 5,202 ms | 80 | [JSON](lighthouse/conversation-populated-mobile-fontswap.json) |

RC-06 asks for a measured 0.000, not merely the ≤ 0.02 CI gate. All six runs
report `cumulative-layout-shift.numericValue = 0` with an empty
`layout-shift-elements` list.

### 5.2 Why there are two sets of runs

**The first four runs do not, on their own, prove anything about the swap.**
On a localhost stack the preloaded woff2 files land about 60 ms in, well
before first contentful paint at 221-784 ms. The page therefore painted in
the webfont from the very first frame: there was no fallback on screen, so
there was no swap, so CLS = 0 is unsurprising and says nothing about the
metric overrides.

Criterion 3 asks for CLS = 0.000 *with fonts swapping*, so the last two runs
use real DevTools throttling (600 ms RTT, 700 kbps, 4× CPU) to push the font
responses past first paint and force the transition:

| Run | FCP | Font responses complete | Swap exercised? | CLS |
|---|---:|---|---|---:|
| `home-mobile-fontswap` | 1,613 ms | 2,007 / 2,042 / 2,255 ms | **yes, all three after FCP** | **0.000** |
| `conversation-populated-mobile-fontswap` | 1,588 ms | 1,995 / 2,030 / 2,250 ms | **yes, all three after FCP** | **0.000** |

Text was painted in the metric-adjusted fallback for roughly 400-670 ms and
then replaced by the webfont, and nothing moved. That is the measurement
RC-06 asked for.

### 5.3 What these runs do not cover

**The mono family never loaded in any run.** Its file is not preloaded, and
no surface on either route currently renders mono text — the seeded report
has no code spans, and the current components do not yet use the mono token.
Three font requests appear in every run, not five. The mono family's
adjusted face is therefore evidenced by §4.4's residual (−0.87 px, 0.00 px
baseline, 0.00 px line box) and not by a Lighthouse CLS number. Once WO-18
ships report code spans and the diagnostics surfaces land, the mono swap
becomes observable and should be re-audited.

**Accessibility and best-practices scores are not this work order's claim.**
They are in the JSON (a11y 94-98, best-practices 100) but WO-02 changed
neither; the `/c/[id]` a11y drop to 94 against the baseline's 98 is the
pre-existing event-log semantics finding, not a typography regression.

### 5.4 Reproducing

```bash
# Local stack on explicit loopback ports, with an unusable model key
ANTHROPIC_API_KEY=local-preview-disabled \
APP_BIND_ADDRESS=127.0.0.1 APP_PORT=18000 \
WEB_BIND_ADDRESS=127.0.0.1 WEB_PORT=13000 \
docker compose up -d --build

# The conversation tables are created lazily on first read
curl -s http://127.0.0.1:13000/api/conversations >/dev/null

docs/revamp/baseline/fixtures/seed-local-baseline.sh

# Simulated throttling (the default Lighthouse profile)
npx --yes lighthouse@13.4.1 'http://127.0.0.1:13000/' \
  --only-categories=performance,accessibility,best-practices \
  --output=json --output-path=/tmp/home-mobile.json \
  --chrome-flags='--headless --no-sandbox --disable-gpu'

# Real throttling, which is what forces the font swap
npx --yes lighthouse@13.4.1 'http://127.0.0.1:13000/' \
  --only-categories=performance \
  --throttling-method=devtools \
  --throttling.requestLatencyMs=600 \
  --throttling.downloadThroughputKbps=700 \
  --throttling.uploadThroughputKbps=700 \
  --throttling.cpuSlowdownMultiplier=4 \
  --output=json --output-path=/tmp/home-mobile-fontswap.json \
  --chrome-flags='--headless --no-sandbox --disable-gpu'

ANTHROPIC_API_KEY=local-preview-disabled \
APP_PORT=18000 WEB_PORT=13000 docker compose down
```

---

## 6. RC-20 — the report italic

**Included, not synthesised.** `Literata-Italic-400.woff2` ships at 20,896 B
and is declared in `web/app/fonts/fonts.ts` at `weight: "400", style:
"italic"`, so `*emphasis*` in a Markdown report renders a drawn italic. RC-20
offered an alternative — accept a synthetic oblique and record a rendered
comparison — and D-010 ruling 7 ratified inclusion as the default. The budget
result makes the choice cost-free: even with the italic, the font row sits at
84.2% of ceiling. No synthetic-oblique comparison was produced, because
nothing was traded away to justify one.

UI and mono carry no italic, per RC-20: nothing in the chrome renders `<em>`.

---

## 7. How the stack is composed, and why

Each `--font-*` token in `web/app/tokens.css` is now three layers:

```css
--font-ui: var(--font-ui-face), "Atkinson Hyperlegible Next Fallback",
           ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
```

1. `var(--font-ui-face)` — the self-hosted subset, declared by
   `next/font/local` in `web/app/fonts/fonts.ts` and scoped by a class on
   `<html>`.
2. `"Atkinson Hyperlegible Next Fallback"` — the metric-adjusted face from
   `web/app/fonts/fallback.css`. This is what paints during the
   `font-display: swap` window.
3. The declared generic stack, verbatim and unchanged, for a platform that
   supplies none of the concrete fonts layer 2 names.

**The bare family name is replaced by the variable rather than kept beside
it.** Leaving `"Literata"` in the stack would let a stale full copy installed
on the reader's machine outrank the subset that was measured, and its metrics
would not be the ones in `fallback.css`. `web/tests/fonts.test.ts` asserts
that no layer is a bare family name.

`design/tokens.json` and `web/lib/tokens.ts` were kept in step with
`tokens.css`; WO-01's parity test (which fails on an orphan in either
direction) passes unchanged.

### Preload

| Family | Preloaded | Why |
|---|---|---|
| UI | yes | sets the chrome; on screen at first paint on both routes |
| Report (roman + italic) | yes | sets the landing prompt and thread titles, both above the fold |
| Mono | **no** | job ids, timestamps and diagnostic rows; never the LCP element on either route |

Preloading is a first-paint priority claim, and with the adjusted fallbacks
in place a late swap costs no layout shift — so the cheaper request ordering
is free. Measured font transfer on a cold load of either route: 76,104 B
across three requests.

### No external font host

Every face is served from `/_next/static/media/`. `fallback.css` contains no
`url()` at all — only `local()`. This is required anyway by the C3 CSP's
`font-src 'self'`, and `web/tests/fonts.test.ts` asserts it.

---

## 8. Hooks left for the work orders downstream

- **WO-23 (budgets).** The font row needs no ratchet: 103,476 B against
  122,880 B. The CSS row moved from 4,288 B to 6,040 B gzip against a 12,288
  B ceiling — still inside, but the headroom is now 6,248 B rather than
  8,000 B, and every subsequent surface work order spends from it.
- **WO-06 / WO-08.** The three tokens are live and resolve; components
  consume them through the Tailwind `font-ui` / `font-report` / `font-mono`
  utilities, never by name. `web/tests/fonts.test.ts` fails any file outside
  the exemption list that writes `font-family`, `fontFamily` or `font-[…]`.
  WO-08 is the next writer of `app/layout.tsx`; the font declarations sit
  beside the pre-paint theme script and neither touches the other.
- **WO-18 (report surface).** Literata italic 400 is available now. When
  report code spans land, the mono swap becomes observable and §5.3's gap
  can be closed.
- **Re-measuring.** If a face is added, replaced or re-subset,
  `node web/scripts/measure-fonts.mjs` regenerates §3 and §4 including the
  verification residual, and fails the run if the budget is exceeded or if
  any face turns out to carry a non-zero `hhea.lineGap`.
