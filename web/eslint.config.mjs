import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

/**
 * Literal colours belong in exactly one file: web/app/tokens.css
 * (04-ARCHITECTURE.md section 6.2 item 4). ESLint never lints CSS, so
 * tokens.css is exempt by the fact that no selector below can reach it;
 * the corresponding assertion for CSS and for every other file type is
 * the repository scan in web/tests/tokens.test.ts.
 *
 * The one documented non-CSS exemption is web/app/icon.svg: a favicon is
 * painted with no document to inherit a custom property from, so its
 * marks carry their hex values inline.
 */
// The lookbehind keeps HTML numeric entities (&#9662;) out of the rule:
// they are marks, not colours, and two legacy components use them.
const HEX =
  "(?<!&)#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-fA-F])";
const FUNCTIONAL = "\\b(?:rgb|rgba|hsl|hsla)\\(";

const NO_LITERAL_COLOUR_MESSAGE =
  "Literal colours are not allowed here. Use a design token: a Tailwind " +
  "utility built from web/lib/tokens.ts (bg-canvas, text-ink-muted, " +
  "border-border-strong) or var(--color-*). web/app/tokens.css is the " +
  "only file in web/ that may contain a colour value.";

const noLiteralColour = [
  `Literal[value=/${HEX}/]`,
  `Literal[value=/${FUNCTIONAL}/]`,
  `TemplateElement[value.raw=/${HEX}/]`,
  `TemplateElement[value.raw=/${FUNCTIONAL}/]`,
].map((selector) => ({ selector, message: NO_LITERAL_COLOUR_MESSAGE }));

/**
 * Allow-listed by path until WO-31 (Legacy removal and ratchet) deletes
 * them. These files predate the token foundation and still style
 * themselves with raw slate/blue Tailwind utilities; none of them trips
 * the rule today, so the list is a guard against WO-31's window rather
 * than a suppression of live errors. Every path is enumerated rather
 * than globbed, so a new file in components/ is covered from its first
 * commit.
 */
/**
 * WO-07 criterion 1. One message for both groups, because the answer is
 * always the same shape: hoist the data into a prop.
 */
const PRIMITIVE_BOUNDARY_MESSAGE =
  "components/primitives/ may not reach the data layer. 04-ARCHITECTURE.md " +
  "§5.1: primitives take plain props and never call a hook that fetches, so " +
  "every state they can be in is reachable by passing props and their " +
  "stories need no MSW and no network. Move the fetch up into a features/ " +
  "component and pass the result down.";

const LEGACY_UNTOKENISED = [
  "app/page.tsx",
  "app/c/**/page.tsx",
  "components/ConversationSidebar.tsx",
  "components/ConversationThread.tsx",
  "components/ConversationsShell.tsx",
  "components/EventLog.tsx",
  "components/ExportDropdown.tsx",
  "components/JobSummary.tsx",
  "components/PlanReview.tsx",
  "components/QueryForm.tsx",
  "components/ReportView.tsx",
];

export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  {
    rules: {
      "react/no-unescaped-entities": "off",
    },
  },
  {
    name: "tokens/no-literal-colour",
    // tests/fixtures is in scope on purpose: web/tests/tokens.test.ts
    // proves the rule by linting a real committed file that really
    // fails. `npm run lint` only walks app/ components/ lib/, so the
    // failing fixture never breaks the repository lint.
    files: [
      "app/**/*.{ts,tsx}",
      "components/**/*.{ts,tsx}",
      "tests/fixtures/**/*.{ts,tsx}",
    ],
    ignores: LEGACY_UNTOKENISED,
    rules: {
      "no-restricted-syntax": ["error", ...noLiteralColour],
    },
  },
  {
    /**
     * WO-07 criterion 1 — the primitives import boundary.
     *
     * 04-ARCHITECTURE.md §5.1 states the layer rule: primitives and patterns
     * "take plain props and never call a hook that fetches. Every state they
     * can be in is reachable by passing props, so their stories need no MSW
     * and no network." That is what makes Storybook cheap, and it is exactly
     * the kind of rule that decays the first time somebody reaches for a
     * job id from inside a Button. Lint is the only place it can hold.
     *
     * `no-restricted-imports` rather than another `no-restricted-syntax`
     * block, deliberately: flat config REPLACES a rule's options rather than
     * merging them, so a second `no-restricted-syntax` entry scoped to
     * components/primitives/** would silently switch the no-literal-colour
     * rule OFF for the newest files in the repository. A different rule
     * cannot collide.
     *
     * tests/fixtures/primitive-*.fixture.tsx are in scope for the same
     * reason WO-01's fixtures are: web/tests/primitives/boundary.test.tsx
     * lints a real committed file that really fails, which is what proves
     * the rule fires rather than merely being configured. `npm run lint`
     * walks only app/ components/ lib/, so the failing fixture never breaks
     * the repository lint.
     */
    name: "primitives/no-data-layer",
    files: [
      "components/primitives/**/*.{ts,tsx}",
      "tests/fixtures/primitive-*.fixture.{ts,tsx}",
    ],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: [
                "@/lib/api",
                "@/lib/api/*",
                "@/lib/api.ts",
                "**/lib/api",
                "**/lib/api/*",
                "**/lib/api.ts",
              ],
              message: PRIMITIVE_BOUNDARY_MESSAGE,
            },
            {
              group: [
                "@/lib/useResearchStream",
                "**/useResearchStream",
                "swr",
                "swr/*",
                "@tanstack/react-query",
                "react-query",
                "msw",
                "msw/*",
              ],
              message: PRIMITIVE_BOUNDARY_MESSAGE,
            },
          ],
        },
      ],
    },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
