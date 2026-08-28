/**
 * Patterns/SectionRail — WO-18 criterion 10, second group.
 *
 * IT IS A SEPARATE GROUP FOR A STATED REASON. The criterion says the rail's
 * "absent and sticky states are not reachable from the reader group", and
 * that is literally true: `ReportReader/Empty` has no briefing so it has no
 * rail either, and `ReportReader/LongWithHeadings` renders a rail that only
 * becomes sticky above 1280px inside a scrolling column. Driving the rail
 * with headings passed straight in is the only way to put `Absent`,
 * `LongSticky` and `ActiveHeading` on screen as themselves — which is what
 * discharges one of RC-10's four uncovered components.
 *
 * `Absent` is the one to read twice. The rail returns `null` for an empty
 * list, so this story is deliberately a story that renders NOTHING inside
 * its frame. A rail that rendered a titled empty box instead would tell a
 * reader that the briefing is broken when it is merely short.
 *
 * The headings below are sample DOCUMENT headings, not product copy: the
 * rail passes a report's own words through verbatim, the way a checkpoint
 * label is passed through (H11). The only product string here is `label`,
 * which comes from `lib/copy/report`.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { REPORT } from "@/lib/copy/report";

import { SectionRail, type ReportHeading } from "./SectionRail";

const SHORT: ReportHeading[] = [
  { id: "what-the-field-measures", text: "What the field measures", level: 2 },
  { id: "where-the-disagreement-is", text: "Where the disagreement is", level: 2 },
  { id: "limits", text: "Limits", level: 2 },
];

const DEEP: ReportHeading[] = [
  { id: "what-the-field-measures", text: "What the field measures", level: 2 },
  { id: "automatic-metrics", text: "Automatic metrics", level: 3 },
  { id: "human-protocols", text: "Human protocols", level: 3 },
  { id: "where-the-disagreement-is", text: "Where the disagreement is", level: 2 },
  { id: "unsupported-but-correct", text: "Unsupported but correct", level: 3 },
  { id: "supported-but-wrong", text: "Supported but wrong", level: 3 },
  { id: "limits", text: "Limits", level: 2 },
];

/** Enough entries that the sticky column has something to hold on to. */
const LONG: ReportHeading[] = Array.from({ length: 18 }, (_, index) => {
  const ordinal = index + 1;
  return {
    id: `section-${ordinal}`,
    text: `${DEEP[index % DEEP.length]?.text ?? "Section"} ${ordinal}`,
    level: (index % 3 === 0 ? 2 : 3) as 2 | 3,
  };
});

const meta = {
  title: "Patterns/SectionRail",
  component: SectionRail,
  args: {
    headings: SHORT,
    label: REPORT.railLabel,
  },
  render: (args) => (
    <div className="p-6">
      <SectionRail {...args} />
    </div>
  ),
} satisfies Meta<typeof SectionRail>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Criterion 4: a heading-free report leaves the rail absent, not shelled. */
export const Absent: Story = { args: { headings: [] } };

export const ShortList: Story = { args: { headings: SHORT } };

/** `h3` entries indent under the `h2` they follow; the tag is the depth. */
export const DeepNesting: Story = { args: { headings: DEEP } };

/**
 * The sticky state. The rail pins itself at 1280px and up (03 §7.5), so the
 * frame below is tall enough to scroll and the viewport toolbar's 1440
 * option is where the behaviour is visible.
 */
export const LongSticky: Story = {
  args: { headings: LONG },
  render: (args) => (
    <div className="flex gap-8 p-6">
      <SectionRail {...args} />
      <div className="h-[160vh] flex-1 rounded-md border border-border-subtle bg-sunken" />
    </div>
  ),
};

/** `aria-current="location"`, plus a rule and full-strength ink (03 §3.4). */
export const ActiveHeading: Story = {
  args: { headings: DEEP, activeId: "human-protocols" },
};

export const Dark: Story = {
  args: { headings: DEEP, activeId: "human-protocols" },
  globals: { theme: "dark" },
};

/** The current section survives without its hue: the rule and weight carry it. */
export const ForcedColours: Story = {
  args: { headings: DEEP, activeId: "human-protocols" },
  globals: { theme: "forced-colors" },
};
