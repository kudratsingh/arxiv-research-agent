/**
 * Foundations/Type — WO-06 exemplar story.
 *
 * The three families and the thirteen scale steps, read straight out of
 * web/lib/tokens.ts. Nothing here names a typeface or a pixel size: the
 * specimens select a family with the `font-ui` / `font-report` /
 * `font-mono` utilities Tailwind builds from the token module, and set
 * `fontSize`/`lineHeight` to `var(--text-*)` references. WO-02's rule is
 * that a family is named in exactly one place -- app/tokens.css composes
 * the stacks, app/fonts/fonts.ts declares the faces -- and
 * web/tests/fonts.test.ts scans every file under web/ to prove it, this
 * one included. The page therefore renders whatever the token layer
 * currently says, which is the only way a specimen can stay honest.
 *
 * The faces are the real ones. `@storybook/nextjs-vite` runs the same
 * `next/font/local` transform Next does, so app/fonts/fonts.ts is imported
 * unchanged and .storybook/decorators/fonts.tsx puts its variable classes on
 * `:root` exactly as app/layout.tsx does — see that file for why a wrapper
 * element would not have worked.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { color, font, layout, space, text, type FontToken, type TextToken } from "../../lib/tokens";

import { FAMILY_CLASS } from "./families";

/* =========================================================================
 * Which ramp belongs to which family. The scale keys carry it in their
 * prefix (03-DESIGN-BRIEF.md section 3.5: three parallel ramps plus
 * display), so this is derived rather than restated.
 * ========================================================================= */

function familyFor(step: TextToken): FontToken {
  if (step.startsWith("mono-")) return "mono";
  if (step.startsWith("ui-")) return "ui";
  return "report";
}

/** What each family is FOR. Which face it is belongs to app/fonts/fonts.ts. */
const FAMILY_NOTE: Record<FontToken, string> = {
  ui: "Chrome, controls, labels and the landing prompt. Chosen for letterform disambiguation at small sizes — read the Il1 / O0 / rn row below.",
  report: "Report bodies, headings and display. The roman is variable across three weights; the italic is a drawn face rather than a synthesised oblique, so emphasis in a Markdown report is real.",
  mono: "Job ids, timestamps and diagnostic rows. Two static weights, and the only family not preloaded — none of what it sets is the LCP element on either route.",
};

const SPECIMEN = "Faithfulness verifier · arXiv:2401.04088 · 12 checkpoints";

/* ========================================================================= */

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
      className={FAMILY_CLASS.ui}
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

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p
      className={FAMILY_CLASS.ui}
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

function TokenLabel({ children }: { children: React.ReactNode }) {
  return (
    <code
      className={FAMILY_CLASS.mono}
      style={{
        fontSize: text["mono-xs"].size,
        lineHeight: text["mono-xs"].line,
        color: color["ink-muted"],
      }}
    >
      {children}
    </code>
  );
}

function Families() {
  const families = Object.keys(font) as FontToken[];
  return (
    <Page>
      <Heading>Families</Heading>
      <Note>
        Three self-hosted latin-subset families. Each token is a three-layer stack: the subset
        woff2 declared by next/font/local, then a metric-adjusted stand-in that paints during
        the swap window, then the generic stack. The label under each specimen is the token, not
        the typeface — the typeface is named in app/tokens.css and nowhere else.
      </Note>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: space["space-6"] }}>
        {families.map((family) => (
          <li
            key={family}
            style={{
              display: "flex",
              flexDirection: "column",
              gap: space["space-2"],
              borderTop: `1px solid ${color["border-subtle"]}`,
              paddingTop: space["space-3"],
            }}
          >
            <TokenLabel>
              {family} — {font[family]}
            </TokenLabel>
            <p
              className={FAMILY_CLASS[family]}
              style={{
                fontSize: text["report-h2"].size,
                lineHeight: text["report-h2"].line,
                margin: 0,
              }}
            >
              {SPECIMEN}
            </p>
            <p
              className={FAMILY_CLASS[family]}
              style={{
                fontSize: text["ui-base"].size,
                lineHeight: text["ui-base"].line,
                margin: 0,
              }}
            >
              ABCDEFGHIJKLM abcdefghijklm 0123456789 Il1 O0 rn m
            </p>
            <Note>{FAMILY_NOTE[family]}</Note>
          </li>
        ))}
      </ul>
    </Page>
  );
}

function Scale() {
  const steps = Object.keys(text) as TextToken[];
  return (
    <Page>
      <Heading>Type scale</Heading>
      <Note>
        Thirteen steps across three ramps plus display. The smallest rendered size anywhere in
        the product is 12px; the baseline&apos;s 10.4px job-id label has no replacement token by
        design. Each specimen carries its own token name, size, line height and — where the
        token declares them — tracking and weight.
      </Note>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: space["space-4"] }}>
        {steps.map((step) => {
          const facets = text[step];
          const family = familyFor(step);
          return (
            <li
              key={step}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: space["space-1"],
                borderTop: `1px solid ${color["border-subtle"]}`,
                paddingTop: space["space-2"],
              }}
            >
              <TokenLabel>
                {step} · {facets.size} / {facets.line}
                {"tracking" in facets ? ` / ${facets.tracking}` : ""}
                {"weight" in facets ? ` / ${facets.weight}` : ""} · {family}
              </TokenLabel>
              <span
                className={FAMILY_CLASS[family]}
                style={{
                  fontSize: facets.size,
                  lineHeight: facets.line,
                  ...("tracking" in facets ? { letterSpacing: facets.tracking } : {}),
                  ...("weight" in facets ? { fontWeight: facets.weight } : {}),
                }}
              >
                {SPECIMEN}
              </span>
            </li>
          );
        })}
      </ul>
    </Page>
  );
}

const meta = {
  title: "Foundations/Type",
  component: Families,
} satisfies Meta<typeof Families>;

export default meta;

type Story = StoryObj<typeof meta>;

/** The three families, with the letterforms the UI ramp was chosen for. */
export const Families_: Story = { name: "Families" };

/** Every step of the scale, at its own size, in its own ramp's family. */
export const Scale_: Story = { name: "Scale", render: () => <Scale /> };
