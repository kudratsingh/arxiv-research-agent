/**
 * Typed token names for the Evidence Workbench.
 *
 * This module is the single source of *names*. It contains NO literal
 * values -- every entry is a `var(--...)` reference resolved by
 * web/app/tokens.css, which is the single source of *values*
 * (04-ARCHITECTURE.md section 6.2 item 2).
 *
 * web/tailwind.config.ts builds theme.extend from this module, so a
 * Tailwind class and a CSS custom property can never disagree, and
 * web/tests/tokens.test.ts asserts bidirectional parity between this
 * module, tokens.css and docs/revamp/design/tokens.json in both themes.
 *
 * Generated shape, hand-maintained: if the brief renames a role, only
 * this file and tokens.css change. No component is touched.
 */

/** Semantic colour roles. 23 in each theme (RC-15). */
export const color = {
  "canvas": "var(--color-canvas)",
  "surface": "var(--color-surface)",
  "sunken": "var(--color-sunken)",
  "ink": "var(--color-ink)",
  "ink-muted": "var(--color-ink-muted)",
  "ink-faint": "var(--color-ink-faint)",
  "ink-disabled": "var(--color-ink-disabled)",
  "border-subtle": "var(--color-border-subtle)",
  "border-strong": "var(--color-border-strong)",
  "primary": "var(--color-primary)",
  "primary-strong": "var(--color-primary-strong)",
  "primary-on": "var(--color-primary-on)",
  "focus": "var(--color-focus)",
  "signature": "var(--color-signature)",
  "signature-text": "var(--color-signature-text)",
  "signature-on": "var(--color-signature-on)",
  "review": "var(--color-review)",
  "review-text": "var(--color-review-text)",
  "review-surface": "var(--color-review-surface)",
  "critical": "var(--color-critical)",
  "critical-text": "var(--color-critical-text)",
  "critical-surface": "var(--color-critical-surface)",
  "critical-on": "var(--color-critical-on)",
} as const;
export type ColorToken = keyof typeof color;

/**
 * Elevation. elev-0 is the norm -- default separation is a 1px
 * border-subtle rule, not a shadow. In dark mode every elevated surface
 * must ALSO step canvas -> surface and carry a border-strong outline,
 * because the dark shadow values carry almost no signal on their own.
 */
export const elevation = {
  "elev-0": "var(--elevation-0)",
  "elev-1": "var(--elevation-1)",
  "elev-2": "var(--elevation-2)",
  "elev-3": "var(--elevation-3)",
} as const;
export type ElevationToken = keyof typeof elevation;

/** Space scale, 4px unit. */
export const space = {
  "space-0": "var(--space-0)",
  "space-05": "var(--space-05)",
  "space-1": "var(--space-1)",
  "space-2": "var(--space-2)",
  "space-3": "var(--space-3)",
  "space-4": "var(--space-4)",
  "space-5": "var(--space-5)",
  "space-6": "var(--space-6)",
  "space-8": "var(--space-8)",
  "space-10": "var(--space-10)",
  "space-12": "var(--space-12)",
  "space-16": "var(--space-16)",
  "space-24": "var(--space-24)",
} as const;
export type SpaceToken = keyof typeof space;

/** Layout constants: rail, measure, gutters, breakpoints. */
export const layout = {
  "gutter-narrow": "var(--layout-gutter-narrow)",
  "gutter-wide": "var(--layout-gutter-wide)",
  "rail-width": "var(--layout-rail-width)",
  "rail-collapsed-width": "var(--layout-rail-collapsed-width)",
  "report-measure": "var(--layout-report-measure)",
  "content-max": "var(--layout-content-max)",
  "breakpoint-sm": "var(--layout-breakpoint-sm)",
  "breakpoint-md": "var(--layout-breakpoint-md)",
  "breakpoint-lg": "var(--layout-breakpoint-lg)",
  "breakpoint-xl": "var(--layout-breakpoint-xl)",
} as const;
export type LayoutToken = keyof typeof layout;

/** Hit targets, control heights, icon and trace mark sizes, focus ring. */
export const size = {
  "target-min": "var(--size-target-min)",
  "target-default": "var(--size-target-default)",
  "target-coarse": "var(--size-target-coarse)",
  "control-height-sm": "var(--size-control-height-sm)",
  "control-height-md": "var(--size-control-height-md)",
  "control-height-lg": "var(--size-control-height-lg)",
  "icon-sm": "var(--size-icon-sm)",
  "icon-md": "var(--size-icon-md)",
  "trace-dot": "var(--size-trace-dot)",
  "trace-rule": "var(--size-trace-rule)",
  "focus-ring-width": "var(--size-focus-ring-width)",
  "focus-ring-offset": "var(--size-focus-ring-offset)",
} as const;
export type SizeToken = keyof typeof size;

/** Radii. Nothing above 6px except radius-dot (a data mark, not a container). */
export const radius = {
  "radius-0": "var(--radius-0)",
  "radius-sm": "var(--radius-sm)",
  "radius-md": "var(--radius-md)",
  "radius-lg": "var(--radius-lg)",
  "radius-dot": "var(--radius-dot)",
} as const;
export type RadiusToken = keyof typeof radius;

/**
 * Font families. WO-02 owns the self-hosted woff2 subsets and the
 * measured fallback metrics; these names resolve to the declared
 * fallback stacks until then.
 */
export const font = {
  "ui": "var(--font-ui)",
  "report": "var(--font-report)",
  "mono": "var(--font-mono)",
} as const;
export type FontToken = keyof typeof font;

/**
 * Type scale. Three parallel ramps (ui-*, report-*, mono-*) plus display.
 * Minimum rendered size is 12px anywhere in the product.
 */
export const text = {
  "ui-xs": { size: "var(--text-ui-xs-size)", line: "var(--text-ui-xs-line)", tracking: "var(--text-ui-xs-tracking)" },
  "ui-sm": { size: "var(--text-ui-sm-size)", line: "var(--text-ui-sm-line)", tracking: "var(--text-ui-sm-tracking)" },
  "ui-base": { size: "var(--text-ui-base-size)", line: "var(--text-ui-base-line)", tracking: "var(--text-ui-base-tracking)" },
  "ui-lg": { size: "var(--text-ui-lg-size)", line: "var(--text-ui-lg-line)", tracking: "var(--text-ui-lg-tracking)" },
  "ui-xl": { size: "var(--text-ui-xl-size)", line: "var(--text-ui-xl-line)", tracking: "var(--text-ui-xl-tracking)" },
  "report-small": { size: "var(--text-report-small-size)", line: "var(--text-report-small-line)" },
  "report-body": { size: "var(--text-report-body-size)", line: "var(--text-report-body-line)" },
  "report-h3": { size: "var(--text-report-h3-size)", line: "var(--text-report-h3-line)", weight: "var(--text-report-h3-weight)" },
  "report-h2": { size: "var(--text-report-h2-size)", line: "var(--text-report-h2-line)", weight: "var(--text-report-h2-weight)" },
  "report-h1": { size: "var(--text-report-h1-size)", line: "var(--text-report-h1-line)", weight: "var(--text-report-h1-weight)" },
  "display": { size: "var(--text-display-size)", line: "var(--text-display-line)", tracking: "var(--text-display-tracking)" },
  "mono-xs": { size: "var(--text-mono-xs-size)", line: "var(--text-mono-xs-line)" },
  "mono-sm": { size: "var(--text-mono-sm-size)", line: "var(--text-mono-sm-line)" },
} as const;
export type TextToken = keyof typeof text;

/** Durations. Five steps: instant is tokens.json's, not the brief table's (RC-02). */
export const duration = {
  "dur-instant": "var(--duration-instant)",
  "dur-fast": "var(--duration-fast)",
  "dur-base": "var(--duration-base)",
  "dur-slow": "var(--duration-slow)",
  "dur-ambient": "var(--duration-ambient)",
} as const;
export type DurationToken = keyof typeof duration;

/** Easing curves. */
export const ease = {
  "ease-standard": "var(--ease-standard)",
  "ease-enter": "var(--ease-enter)",
  "ease-exit": "var(--ease-exit)",
} as const;
export type EaseToken = keyof typeof ease;

/**
 * StatusBanner severities, mapped onto the roles that exist (RC-17).
 *
 * The palette deliberately ships neither `success` nor `warning` -- "A
 * second accent colour for 'success'. Cut." (03-DESIGN-BRIEF.md
 * Appendix) -- so no new hue is invented for a severity. What actually
 * differentiates the five is that each carries a distinct word and a
 * distinct mark shape (03 section 3.4); colour is the third signal, never
 * the only one. WO-12 owns the banner itself and consumes this map.
 */
export const STATUS_SEVERITY_ROLE = {
  info: "primary",
  review: "review",
  live: "signature",
  warning: "review",
  critical: "critical",
} as const satisfies Record<string, ColorToken>;
export type StatusSeverity = keyof typeof STATUS_SEVERITY_ROLE;

/* =========================================================================
 * Theme mechanism
 * ========================================================================= */

/**
 * The persisted client-side preferences, in full (RC-05).
 *
 * | Key                          | Values                      | Owner |
 * |------------------------------|-----------------------------|-------|
 * | `arxiv-agent.theme`          | "light" \| "dark" \| "system" | WO-01 |
 * | `arxiv-agent.rail-collapsed` | "1" \| "0"                   | WO-08 |
 *
 * These are the ONLY two keys the product may persist, and both are
 * cosmetic: no job id, plan, checkpoint or query is ever written to
 * browser storage, so nothing in storage can outlive
 * `api_job_retention_sec` (04-ARCHITECTURE.md section 4.4).
 * `arxiv-agent.rail-collapsed` is reserved here so the namespace is
 * documented in one place; WO-08 implements it.
 */
export const THEME_STORAGE_KEY = "arxiv-agent.theme";

/** Reserved for WO-08's rail collapse toggle. Declared, not yet read. */
export const RAIL_COLLAPSED_STORAGE_KEY = "arxiv-agent.rail-collapsed";

/** What the user can choose. "system" defers to prefers-color-scheme. */
export const THEME_PREFERENCES = ["light", "dark", "system"] as const;
export type ThemePreference = (typeof THEME_PREFERENCES)[number];

/** What actually gets written to `data-theme`. */
export type ResolvedTheme = "light" | "dark";

/** The attribute the pre-paint script writes the *resolved* theme to. */
export const THEME_ATTRIBUTE = "data-theme";

/**
 * The attribute the pre-paint script writes the *raw* preference to, so a
 * theme control (WO-08) can distinguish an explicit "light" from a
 * "system" that currently resolves to light, and so the media-query
 * listener knows whether it is still allowed to follow the OS.
 */
export const THEME_PREFERENCE_ATTRIBUTE = "data-theme-preference";

/**
 * The pre-paint theme script, as source text for an inline
 * `<script>` in the root layout.
 *
 * It must run before first paint, so it is inline and synchronous rather
 * than a module: a deferred script would paint the light theme first and
 * flash. It writes BOTH attributes, which is what keeps Tailwind's
 * `dark:` variant -- configured as `[data-theme="dark"]` -- working for
 * a user who never opens the theme control.
 *
 * Everything is wrapped in try/catch because `localStorage` throws
 * outright in a partitioned or storage-blocked context; the failure mode
 * is the light theme plus the `prefers-color-scheme` block in
 * tokens.css, never an exception before first paint.
 *
 * WO-21 asserts the no-flash property in Playwright by loading with the
 * key pre-seeded to "dark" and sampling the painted background colour.
 * C3 (the CSP in 05-MIGRATION.md section 3) must add this script's nonce
 * once `web/middleware.ts` exists; it is the only inline script in the
 * document.
 */
export const themeInitScript =
  "(function(){try{" +
  `var k=${JSON.stringify(THEME_STORAGE_KEY)};` +
  `var t=${JSON.stringify(THEME_ATTRIBUTE)};` +
  `var q=${JSON.stringify(THEME_PREFERENCE_ATTRIBUTE)};` +
  `var v=${JSON.stringify(THEME_PREFERENCES)};` +
  "var s=window.localStorage.getItem(k);" +
  'var p=v.indexOf(s)<0?"system":s;' +
  'var m=window.matchMedia("(prefers-color-scheme: dark)");' +
  "var d=document.documentElement;" +
  'var a=function(){d.setAttribute(t,p==="system"?(m.matches?"dark":"light"):p);};' +
  "a();d.setAttribute(q,p);" +
  'if(p==="system"&&m.addEventListener){m.addEventListener("change",a);}' +
  "}catch(e){}})();";
