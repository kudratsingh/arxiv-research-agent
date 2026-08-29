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
  // `preload: false`, for the reason stated for mono below and measured on
  // this family in the Gate 3 rerun. `--font-report` has exactly one consumer
  // in the whole product — `.ew-report`, the reading column
  // (app/tokens.css) — so it sets no pixel of any route's first paint: not
  // the landing prompt (that is `--font-ui`, inherited from `body`), not the
  // chrome, not the thread header. Preloading it put 55,612 B of woff2 at
  // VeryHigh priority ahead of the render-blocking CSS on EVERY navigation,
  // including `/`, where a briefing cannot exist. The adjusted fallbacks in
  // ./fallback.css are what make the later swap free.
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
  display: "swap",
  preload: false,
  adjustFontFallback: false,
});

/** The class list that puts all three variables in scope. */
export const fontVariables = [fontUi.variable, fontReport.variable, fontMono.variable].join(" ");
