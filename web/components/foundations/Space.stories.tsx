/**
 * Foundations/Space — WO-06 exemplar story.
 *
 * The 4px space ramp, the radii, the hit-target and control sizes, the
 * layout constants and the elevation set, all read out of
 * web/lib/tokens.ts. Every bar's width, every corner and every shadow is a
 * `var(--...)` reference; the story holds no measurement of its own.
 *
 * Worth reading in dark mode: elevation carries almost no signal there,
 * which is why the token module's own comment requires an elevated surface
 * to step canvas → surface AND carry a border-strong outline rather than
 * relying on the shadow.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import {
  color,
  elevation,
  layout,
  radius,
  size,
  space,
  text,
  type ElevationToken,
  type LayoutToken,
  type RadiusToken,
  type SizeToken,
  type SpaceToken,
} from "../../lib/tokens";

import { FAMILY_CLASS } from "./families";

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

function TokenLabel({ children, width }: { children: React.ReactNode; width?: string }) {
  return (
    <code
      className={FAMILY_CLASS.mono}
      style={{
        fontSize: text["mono-xs"].size,
        lineHeight: text["mono-xs"].line,
        color: color["ink-muted"],
        ...(width === undefined ? {} : { minWidth: width, flex: "0 0 auto" }),
      }}
    >
      {children}
    </code>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return (
    <li style={{ display: "flex", alignItems: "center", gap: space["space-3"] }}>{children}</li>
  );
}

function List({ children }: { children: React.ReactNode }) {
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: space["space-2"] }}>
      {children}
    </ul>
  );
}

function SpaceScale() {
  const steps = Object.keys(space) as SpaceToken[];
  return (
    <Page>
      <Heading>Space</Heading>
      <Note>
        A 4px ramp with one half-step. The scale is value-identical to Tailwind&apos;s default at
        every shared key, so `p-4` and `var(--space-4)` are the same 16px — the tokens reroute
        the utilities rather than redefining them.
      </Note>
      <List>
        {steps.map((step) => (
          <Row key={step}>
            <TokenLabel width={size["control-height-lg"]}>{step}</TokenLabel>
            <span
              style={{
                background: color.primary,
                width: space[step],
                height: space["space-3"],
                borderRadius: radius["radius-sm"],
                // A zero-width bar is still a row; the outline says so.
                outline: `1px solid ${color["border-strong"]}`,
                flex: "0 0 auto",
              }}
            />
            <TokenLabel>{space[step]}</TokenLabel>
          </Row>
        ))}
      </List>
    </Page>
  );
}

function Radii() {
  const radii = Object.keys(radius) as RadiusToken[];
  return (
    <Page>
      <Heading>Radii</Heading>
      <Note>
        Nothing above 6px except radius-dot, which is reserved for the trace spine&apos;s
        checkpoint marks — a data mark, not a container.
      </Note>
      <List>
        {radii.map((step) => (
          <Row key={step}>
            <TokenLabel width={size["control-height-lg"]}>{step}</TokenLabel>
            <span
              style={{
                background: color.surface,
                border: `1px solid ${color["border-strong"]}`,
                borderRadius: radius[step],
                width: space["space-12"],
                height: space["space-12"],
                flex: "0 0 auto",
              }}
            />
            <TokenLabel>{radius[step]}</TokenLabel>
          </Row>
        ))}
      </List>
    </Page>
  );
}

function Sizes() {
  const sizes = Object.keys(size) as SizeToken[];
  const layouts = Object.keys(layout) as LayoutToken[];
  return (
    <Page>
      <Heading>Sizes and layout constants</Heading>
      <Note>
        Hit targets, control heights, icon and trace-mark sizes, and the focus ring. These are
        consumed as custom properties rather than Tailwind utilities — several would collide
        with a colour utility if mapped by name.
      </Note>
      <List>
        {sizes.map((step) => (
          <Row key={step}>
            <TokenLabel width={layout["rail-collapsed-width"]}>{step}</TokenLabel>
            <span
              style={{
                background: color.sunken,
                border: `1px solid ${color["border-subtle"]}`,
                width: size[step],
                height: size[step],
                flex: "0 0 auto",
              }}
            />
            <TokenLabel>{size[step]}</TokenLabel>
          </Row>
        ))}
      </List>
      <Heading>Layout</Heading>
      <Note>
        The rail widths, the gutters, the report measure and the four breakpoints. The
        breakpoints are deliberately not mapped into Tailwind&apos;s `screens`: its default `sm`
        is 640px against this scale&apos;s 480px, and overriding it would move the surviving
        legacy `sm:` utilities.
      </Note>
      <List>
        {layouts.map((step) => (
          <Row key={step}>
            <TokenLabel width={layout["rail-collapsed-width"]}>{step}</TokenLabel>
            <TokenLabel>{layout[step]}</TokenLabel>
          </Row>
        ))}
      </List>
    </Page>
  );
}

function Elevation() {
  const levels = Object.keys(elevation) as ElevationToken[];
  return (
    <Page>
      <Heading>Elevation</Heading>
      <Note>
        elev-0 is the norm: default separation is a 1px border-subtle rule, not a shadow. In
        dark mode the shadow values carry almost no signal, which is why an elevated surface
        must also step canvas → surface and carry a border-strong outline. Switch the theme
        toolbar to see how little the shadow alone does.
      </Note>
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: space["space-4"],
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
          gap: space["space-6"],
        }}
      >
        {levels.map((level) => (
          <li
            key={level}
            style={{
              background: color.surface,
              boxShadow: elevation[level],
              border: `1px solid ${color["border-subtle"]}`,
              borderRadius: radius["radius-lg"],
              padding: space["space-4"],
              display: "flex",
              flexDirection: "column",
              gap: space["space-1"],
            }}
          >
            <TokenLabel>{level}</TokenLabel>
            <span
              className={FAMILY_CLASS.ui}
              style={{
                fontSize: text["ui-sm"].size,
                lineHeight: text["ui-sm"].line,
              }}
            >
              Raised surface
            </span>
          </li>
        ))}
      </ul>
    </Page>
  );
}

const meta = {
  title: "Foundations/Space",
  component: SpaceScale,
} satisfies Meta<typeof SpaceScale>;

export default meta;

type Story = StoryObj<typeof meta>;

/** The 4px ramp, one bar per step. */
export const Scale: Story = {};

/** Five radii, all of them small. */
export const Radius: Story = { render: () => <Radii /> };

/** Hit targets, control heights, marks, and the layout constants. */
export const SizesAndLayout: Story = { render: () => <Sizes /> };

/** Four elevation steps — and the reason dark mode cannot rely on them. */
export const ElevationScale: Story = { render: () => <Elevation /> };
