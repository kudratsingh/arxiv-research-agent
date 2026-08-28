/**
 * Foundations/Colour — WO-06 exemplar story, and the evidence for
 * acceptance criterion 5.
 *
 * Every value on this page comes from web/lib/tokens.ts. There is not a
 * single literal colour in the file, which the ESLint no-restricted-syntax
 * rule (eslint.config.mjs, applied to components/**) and the repository-wide
 * scan in web/tests/tokens.test.ts both enforce -- a swatch here is a
 * `var(--color-*)` reference resolved by app/tokens.css, exactly as a
 * component's would be.
 *
 * Read it with the theme toolbar. Light and dark flip the same `data-theme`
 * attribute the product's pre-paint script writes, so the swatches change
 * because tokens.css changed, not because the story did. Forced colours
 * collapses all twenty-three roles onto the system palette: that is the
 * baseline RC-17 is argued from, and the reason every status row below
 * carries a word and a mark of its own.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect } from "storybook/test";

import {
  FONT_VARIABLE_CLASSES,
  FORCED_COLORS_ATTRIBUTE,
  REDUCED_MOTION_ATTRIBUTE,
  type MotionPreference,
  type StorybookTheme,
} from "../../.storybook/decorators";
import {
  STATUS_SEVERITY_ROLE,
  THEME_ATTRIBUTE,
  THEME_PREFERENCE_ATTRIBUTE,
  color,
  layout,
  radius,
  space,
  text,
  type ColorToken,
  type StatusSeverity,
} from "../../lib/tokens";

import { FAMILY_CLASS } from "./families";

/* =========================================================================
 * Groups. The order is app/tokens.css's, so a reader can hold the two
 * files side by side.
 * ========================================================================= */

const GROUPS: ReadonlyArray<{ heading: string; note: string; tokens: readonly ColorToken[] }> = [
  {
    heading: "Surfaces",
    note: "Default separation is a 1px border-subtle rule, not a shadow.",
    tokens: ["canvas", "surface", "sunken"],
  },
  {
    heading: "Ink",
    note: "Four weights. ink-disabled is the only one that may drop below AA, and only on disabled controls.",
    tokens: ["ink", "ink-muted", "ink-faint", "ink-disabled"],
  },
  {
    heading: "Rules",
    note: "border-subtle is the norm; border-strong is for a surface that must read as raised in dark mode.",
    tokens: ["border-subtle", "border-strong"],
  },
  {
    heading: "Primary and focus",
    note: "primary-on is the text colour that sits on a primary fill.",
    tokens: ["primary", "primary-strong", "primary-on", "focus"],
  },
  {
    heading: "Signature (live)",
    note: "The -text variant is the one that carries body copy; the base is for fills and marks.",
    tokens: ["signature", "signature-text", "signature-on"],
  },
  {
    heading: "Review",
    note: "Also carries the warning severity — no second hue was invented for it (RC-17).",
    tokens: ["review", "review-text", "review-surface"],
  },
  {
    heading: "Critical",
    note: "The only role permitted to interrupt.",
    tokens: ["critical", "critical-text", "critical-surface", "critical-on"],
  },
];

/* =========================================================================
 * Status marks. RC-17: five severities, three hues. What separates them is
 * the word and the shape, both of which survive a forced-colors substitution
 * because the shapes are drawn in `currentColor`.
 * ========================================================================= */

const SEVERITY_WORD: Record<StatusSeverity, string> = {
  info: "Note",
  review: "Awaiting review",
  live: "Live",
  warning: "Degraded",
  critical: "Failed",
};

/** One mark per severity. No two share a silhouette. */
function SeverityMark({ severity }: { severity: StatusSeverity }) {
  const common = { width: 14, height: 14, viewBox: "0 0 14 14", "aria-hidden": true } as const;
  switch (severity) {
    case "info":
      // Hollow ring.
      return (
        <svg {...common}>
          <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      );
    case "review":
      // Diamond, hollow — a decision is pending, nothing is filled in yet.
      return (
        <svg {...common}>
          <path d="M7 1 L13 7 L7 13 L1 7 Z" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      );
    case "live":
      // Filled dot — the same mark the trace spine uses for a checkpoint.
      return (
        <svg {...common}>
          <circle cx="7" cy="7" r="4.5" fill="currentColor" />
        </svg>
      );
    case "warning":
      // Triangle. Shares `review`'s hue and shares nothing else.
      return (
        <svg {...common}>
          <path d="M7 1.5 L13 12.5 L1 12.5 Z" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      );
    case "critical":
      // Cross.
      return (
        <svg {...common}>
          <path
            d="M2.5 2.5 L11.5 11.5 M11.5 2.5 L2.5 11.5"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
          />
        </svg>
      );
  }
}

/* =========================================================================
 * Presentation. Layout comes from the space and type tokens too, so the
 * page is a demonstration of the whole token layer, not only the palette.
 * ========================================================================= */

function Page({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        padding: space["space-6"],
        display: "flex",
        flexDirection: "column",
        gap: space["space-6"],
        color: color.ink,
        background: color.canvas,
        minHeight: "100%",
      }}
    >
      {children}
    </div>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <h2
      style={{
        fontSize: text["ui-xl"].size,
        lineHeight: text["ui-xl"].line,
        letterSpacing: text["ui-xl"].tracking,
        margin: 0,
      }}
    >
      {children}
    </h2>
  );
}

function Subheading({ children }: { children: React.ReactNode }) {
  return (
    <h3
      style={{
        fontSize: text["ui-lg"].size,
        lineHeight: text["ui-lg"].line,
        letterSpacing: text["ui-lg"].tracking,
        margin: 0,
      }}
    >
      {children}
    </h3>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p
      style={{
        fontSize: text["ui-sm"].size,
        lineHeight: text["ui-sm"].line,
        color: color["ink-muted"],
        margin: 0,
        maxWidth: layout["report-measure"],
      }}
    >
      {children}
    </p>
  );
}

function Swatch({ token }: { token: ColorToken }) {
  return (
    <li style={{ display: "flex", alignItems: "center", gap: space["space-3"] }}>
      {/* The outline is what keeps the tile visible once every fill has
       * collapsed to Canvas under forced colours. */}
      <span
        style={{
          background: color[token],
          border: `1px solid ${color["border-strong"]}`,
          borderRadius: radius["radius-sm"],
          width: space["space-16"],
          height: space["space-8"],
          flex: "0 0 auto",
        }}
      />
      <span style={{ display: "flex", flexDirection: "column" }}>
        <code
          className={FAMILY_CLASS.mono}
          style={{
            fontSize: text["mono-sm"].size,
            lineHeight: text["mono-sm"].line,
          }}
        >
          {token}
        </code>
        <code
          className={FAMILY_CLASS.mono}
          style={{
            fontSize: text["mono-xs"].size,
            lineHeight: text["mono-xs"].line,
            color: color["ink-muted"],
          }}
        >
          {color[token]}
        </code>
      </span>
    </li>
  );
}

function Roles() {
  return (
    <Page>
      <Heading>Colour roles</Heading>
      <Note>
        Twenty-three semantic roles, in both themes. Each tile is the
        <code className={FAMILY_CLASS.mono}> var(--color-*) </code>
        reference printed beneath it — nothing here holds a value. Switch the theme
        toolbar to see app/tokens.css resolve the same names differently.
      </Note>
      {GROUPS.map((group) => (
        <section key={group.heading} style={{ display: "flex", flexDirection: "column", gap: space["space-3"] }}>
          <Subheading>{group.heading}</Subheading>
          <Note>{group.note}</Note>
          <ul
            style={{
              listStyle: "none",
              margin: 0,
              padding: 0,
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
              gap: space["space-3"],
            }}
          >
            {group.tokens.map((token) => (
              <Swatch key={token} token={token} />
            ))}
          </ul>
        </section>
      ))}
    </Page>
  );
}

function StatusSeverities() {
  const severities = Object.keys(STATUS_SEVERITY_ROLE) as StatusSeverity[];
  return (
    <Page>
      <Heading>Status is never colour alone</Heading>
      <Note>
        Five severities, three hues: RC-17 maps warning onto the review role rather than
        inventing a fourth. What actually separates them is the word and the mark, which is
        why both are drawn here and why the forced-colours theme — where all five resolve to
        the same CanvasText — is still readable.
      </Note>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: space["space-3"] }}>
        {severities.map((severity) => {
          const role = STATUS_SEVERITY_ROLE[severity];
          return (
            <li
              key={severity}
              style={{
                display: "flex",
                alignItems: "center",
                gap: space["space-3"],
                padding: space["space-3"],
                border: `1px solid ${color["border-subtle"]}`,
                borderRadius: radius["radius-md"],
                background: color.surface,
              }}
            >
              <span style={{ color: color[role], display: "inline-flex", flex: "0 0 auto" }}>
                <SeverityMark severity={severity} />
              </span>
              <span
                style={{
                  fontSize: text["ui-base"].size,
                  lineHeight: text["ui-base"].line,
                  fontWeight: 600,
                  minWidth: "16ch",
                }}
              >
                {SEVERITY_WORD[severity]}
              </span>
              <code
                className={FAMILY_CLASS.mono}
                style={{
                  fontSize: text["mono-xs"].size,
                  lineHeight: text["mono-xs"].line,
                  color: color["ink-muted"],
                }}
              >
                {severity} → {role}
              </code>
            </li>
          );
        })}
      </ul>
    </Page>
  );
}

/* =========================================================================
 * The decorator assertion.
 *
 * Criterion 1 asks that the theme toolbar flip "the same data-theme
 * attribute the product uses, so token CSS responds identically". A story
 * that merely looks right in a screenshot proves neither half of that. This
 * play function reads the active toolbar globals and asserts both:
 *
 *   1. the decorators wrote the attributes web/lib/tokens.ts exports -- the
 *      product's own mechanism, not a Storybook-only one;
 *   2. app/tokens.css answered. `getComputedStyle` on :root is what the
 *      browser would resolve for any component, so this is the token layer
 *      responding, not a restatement of it.
 *
 * No token VALUE is written down. The dark branch flips the attribute back
 * and forth and asserts only that the two themes differ, which is the whole
 * claim; the forced-colours branch asserts the system-colour KEYWORDS,
 * which are not values either. web/tests/tokens.test.ts owns the values.
 *
 * This is the only per-story wiring in the repository, and note what it is
 * not: it does not opt the story into anything. All three toolbars are
 * already applied with none of it -- see .storybook/preview.tsx.
 * ========================================================================= */

// Typed structurally rather than as `Story["play"]`: `meta` carries this
// function, so naming the type it derives from would be circular.
const assertGlobalDecorators = async ({ globals }: { globals: Record<string, unknown> }) => {
  const theme = globals["theme"] as StorybookTheme;
  const motion = globals["motion"] as MotionPreference;
  const root = document.documentElement;
  const resolved = theme === "dark" ? "dark" : "light";
  const read = (property: string) =>
    getComputedStyle(root).getPropertyValue(property).trim();

  /* --- the attributes ------------------------------------------------- */
  await expect(root.getAttribute(THEME_ATTRIBUTE)).toBe(resolved);
  await expect(root.getAttribute(THEME_PREFERENCE_ATTRIBUTE)).toBe(resolved);
  await expect(root.hasAttribute(FORCED_COLORS_ATTRIBUTE)).toBe(theme === "forced-colors");
  await expect(root.hasAttribute(REDUCED_MOTION_ATTRIBUTE)).toBe(motion === "reduce");

  // The font decorator puts next/font/local's variable classes on :root,
  // which is the only element they work from -- see decorators/fonts.tsx.
  for (const className of FONT_VARIABLE_CLASSES) {
    await expect(root.classList.contains(className)).toBe(true);
  }

  /* --- the token layer's answer --------------------------------------- */
  if (theme === "forced-colors") {
    // The system palette a forced-colors user agent supplies, and the
    // shadows it refuses to paint.
    await expect(read("--color-canvas")).toBe("Canvas");
    await expect(read("--color-ink")).toBe("CanvasText");
    await expect(read("--elevation-1")).toBe("none");
  } else {
    // Flip the product's own attribute and watch tokens.css answer
    // differently, then flip it back and watch it answer the same.
    const before = read("--color-canvas");
    root.setAttribute(THEME_ATTRIBUTE, resolved === "dark" ? "light" : "dark");
    const other = read("--color-canvas");
    root.setAttribute(THEME_ATTRIBUTE, resolved);
    await expect(other).not.toBe(before);
    await expect(read("--color-canvas")).toBe(before);
  }

  // tokens.json motion.reducedMotion.policy item 1: every duration
  // collapses to 1ms. app/tokens.css does it behind the media query;
  // .storybook/preview.css does it behind the attribute.
  await expect(read("--duration-base") === "1ms").toBe(motion === "reduce");
};

const meta = {
  title: "Foundations/Colour",
  component: Roles,
  play: assertGlobalDecorators,
} satisfies Meta<typeof Roles>;

export default meta;

type Story = StoryObj<typeof meta>;

/** All twenty-three roles, grouped as app/tokens.css groups them. */
export const Palette: Story = {};

/**
 * The same story with the theme toolbar pinned. `globals` on a story is
 * Storybook's own mechanism, so this is the toolbar's value, not a second
 * path into the decorator.
 */
export const PaletteDark: Story = { globals: { theme: "dark" } };

/**
 * Criterion 5. Every fill has collapsed onto the system palette; what is
 * left is the outline on each tile and the token name beside it, both of
 * which still read. Compare with Palette: the page loses its hues and
 * keeps its information.
 */
export const PaletteForcedColors: Story = { globals: { theme: "forced-colors" } };

/**
 * The third toolbar, on the story that carries the decorator assertions.
 * A palette does not move, so what this proves is the decorator and not the
 * palette: every `--duration-*` is 1ms while it is selected.
 */
export const PaletteReducedMotion: Story = { globals: { motion: "reduce" } };

/** RC-17's word + mark + colour rule, with all three signals present. */
export const Severities: Story = {
  render: () => <StatusSeverities />,
};

/**
 * RC-17 with the colour taken away. info, review, live, warning and
 * critical all resolve to CanvasText here; the word and the mark are the
 * whole difference, which is the rule's justification rendered.
 */
export const SeveritiesForcedColors: Story = {
  render: () => <StatusSeverities />,
  globals: { theme: "forced-colors" },
};
