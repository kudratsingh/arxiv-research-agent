/**
 * WO-02 — the three self-hosted families.
 *
 * Every face is a latin-subset woff2 built from a pinned google/fonts
 * artifact and committed beside this file with its SIL OFL 1.1 licence. The
 * build command, the source commit, the per-face byte table and the measured
 * fallback metrics are in docs/revamp/evidence/gate-3/fonts.md; they can be
 * regenerated with `node scripts/measure-fonts.mjs`.
 *
 * `next/font/local` hashes each family into its own name and emits the
 * @font-face rules, so nothing is fetched from a font host -- which the C3
 * CSP's `font-src 'self'` would refuse anyway. Each object below exposes a
 * CSS variable that app/tokens.css puts at the head of the matching
 * `--font-*` stack.
 *
 * Two choices worth stating, because neither is the library default:
 *
 * `adjustFontFallback: false` -- next/font can synthesise metric overrides,
 * but only against Arial or Times New Roman and only through its own hidden
 * fallback family. RC-06 asks for measured numbers against the fallback
 * stack this product actually declares, so the adjusted faces are ours and
 * live in ./fallback.css.
 *
 * `preload: false` on mono -- preloading is a first-paint priority claim.
 * The UI and report families set the landing prompt and the chrome, so they
 * earn it; the mono family sets job ids, timestamps and diagnostic rows,
 * none of which is the LCP element on either route. With the adjusted
 * fallbacks in place a late swap costs no layout shift, so the cheaper
 * request ordering is free.
 *
 * AMENDED 2026-09-04 — known-gap §18. The paragraph above is kept, because
 * the measurement in it is still why `preload: false` is cheap; what it now
 * gets wrong is which routes touch which family. WO-W12 (#138) put
 * `LearnLandingEntry` on the landing route, and that card is deliberately
 * typeset in the visual language of the learn surface it teases —
 * `font-report` on its heading, `font-mono` on its eyebrow. So the report
 * and mono families do set pixels on `/`, and mono sets more than job ids,
 * timestamps and diagnostic rows. `preload: false` still holds for both, on
 * a narrower claim; the numbers and the owner's ruling are in the note on
 * `fontReport` below.
 */

import localFont from "next/font/local";

/**
 * UI / body. One variable face carrying the 400, 600 and 700 the design
 * uses (03-DESIGN-BRIEF.md section 3.5); the upstream axis runs 200-800 and
 * is clipped to the used span.
 */
export const fontUi = localFont({
  src: [
    {
      path: "./AtkinsonHyperlegibleNext-400-700.woff2",
      weight: "400 700",
      style: "normal",
    },
  ],
  variable: "--font-ui-face",
  // `preload: true` STAYS, and it was re-measured rather than assumed. This
  // family is `body`'s, so it draws every route's first paint; dropping its
  // preload was tried on the Gate 3 rerun branch and made things worse on
  // both budgets at once — `/` went from LCP 1.37 s to 2.35 s and picked up
  // CLS 0.00618, because the swap then lands after the first contentful
  // paint instead of before it. The report family below is the opposite case
  // and the note there says why.
  display: "swap",
  preload: true,
  adjustFontFallback: false,
});

/**
 * Report / display. The roman is variable across 400-600; the italic is a
 * single pinned 400 face, added under RC-20 so `*emphasis*` in a Markdown
 * report renders a drawn italic instead of a synthesised oblique.
 *
 * Both faces pin Literata's optical-size axis at 17, the report body size.
 * Keeping the axis live would have cost another 17,592 B -- 98.2% of the
 * whole font budget -- for optical compensation at the two larger sizes
 * only; fonts.md records the measurement behind that trade.
 */
export const fontReport = localFont({
  src: [
    {
      path: "./Literata-400-600.woff2",
      weight: "400 600",
      style: "normal",
    },
    {
      path: "./Literata-Italic-400.woff2",
      weight: "400",
      style: "italic",
    },
  ],
  variable: "--font-report-face",
  // `preload: false`. The paragraph that follows is the WO-02 / Gate 3
  // record, retained; read the CORRECTED note after it before relying on its
  // premise.
  //
  // `preload: false`, for the reason stated for mono below and measured on
  // this family in the Gate 3 rerun. `--font-report` has exactly one consumer
  // in the whole product — `.ew-report`, the reading column
  // (app/tokens.css) — so it sets no pixel of any route's first paint: not
  // the landing prompt (that is `--font-ui`, inherited from `body`), not the
  // chrome, not the thread header. Preloading it put 55,612 B of woff2 at
  // VeryHigh priority ahead of the render-blocking CSS on EVERY navigation,
  // including `/`, where a briefing cannot exist. The adjusted fallbacks in
  // ./fallback.css are what make the later swap free.
  //
  // CORRECTED 2026-09-04 — known-gap §18. "Exactly one consumer" and "not the
  // landing prompt" stopped being true at WO-W12 (#138). Since that work
  // order `components/features/LearnLandingEntry.tsx` sits on `/` and is the
  // landing route's only consumer of `--font-report` and `--font-mono`:
  // `font-report text-report-h2` on its heading, `font-mono text-mono-xs` on
  // its eyebrow. The card quotes the typography of the learn surface it
  // teases, so those two faces are on `/` by design. (`.ew-report` is not the
  // only consumer anywhere either — the `/learn/**` headings take
  // `font-report` too.)
  //
  // What that costs `/`, measured on the seeded stack and reported in #159:
  //
  //   font requests   1 (20,331 B, preloaded)  ->  3 (69,621 B, of which
  //                   49,290 B at VeryHigh, discovered after the CSS parse)
  //   total-byte-weight   205,331 B  ->  262,231 B  (+27.7 %)
  //   mainthread-work-breakdown   220 ms  ->  276 ms
  //   bootup-time   98 ms  ->  124 ms
  //
  // `preload: false` still holds, but on a narrower claim than the one above:
  // neither face paints `/`'s LCP element. With #159's `prefetch={false}` on
  // that card, `/` is back at the LCP floor — 1360 ms median even at ×20 CPU
  // slowdown, `bf-cache` 1 — so these late-discovered bytes cost no
  // assertion, and `npm run budgets` passes 9/9 (`/` 162,913 B of 166,912;
  // fonts 103,476 B of 109,568). The adjusted fallbacks in ./fallback.css are
  // still what make the late swap free.
  //
  // OWNER'S RULING, 2026-09-04: accepted. The bytes stay — they are inside
  // every asserted ceiling. The alternative, restyling the landing card away
  // from the learn surface's typography so `/` fetches one face again, was
  // declined.
  display: "swap",
  preload: false,
  adjustFontFallback: false,
});

/**
 * Utility / data. IBM Plex Mono has no upstream variable font, so 400 and
 * 500 ship as two static faces.
 */
export const fontMono = localFont({
  src: [
    { path: "./IBMPlexMono-400.woff2", weight: "400", style: "normal" },
    { path: "./IBMPlexMono-500.woff2", weight: "500", style: "normal" },
  ],
  variable: "--font-mono-face",
  // `preload: false` — the header's paragraph, as amended 2026-09-04. This
  // family still paints no route's LCP element, but since WO-W12 (#138) it is
  // no longer confined to job ids, timestamps and diagnostic rows: it also
  // sets the landing card's eyebrow, which is why `/` fetches it at all. The
  // measurement and the owner's ruling are on `fontReport` above.
  display: "swap",
  preload: false,
  adjustFontFallback: false,
});

/** The class list that puts all three variables in scope. */
export const fontVariables = [fontUi.variable, fontReport.variable, fontMono.variable].join(" ");
