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

/**
 * WO-12 criterion 1 — the copy dictionary is the single edit site.
 *
 * 03-DESIGN-BRIEF.md §5.5's copy rules and 04-ARCHITECTURE.md §9.1's
 * honesty rules are rules about SENTENCES. `web/tests/copy/forbidden.test.ts`
 * can prove that no sentence in web/lib/copy/ says "currently running", but
 * it cannot prove anything about a sentence typed straight into a JSX body —
 * and a rule that only holds for the strings somebody remembered to put in
 * the dictionary is not a rule. This is the half of the enforcement that
 * lint has to carry.
 *
 * SCOPE, EXACTLY. Only text that is RENDERED. `aria-label`, `title`,
 * `data-*`, class names, `key`s and every other non-rendered string are out
 * of scope on purpose: they are not copy, and a rule that flagged them
 * would be routed around with a variable inside a week. The rule fires on
 * five shapes — JSX text nodes, and string literals reaching a child slot
 * directly, through `?:`, through `&&`/`??`, or through a concatenation.
 *
 * NO ALLOW-LIST, AND NO PER-FILE EXEMPTION. WO-08's ThemeToggle and
 * ThreadDrawer land in these two directories concurrently; the coordination
 * is the rule's shape, not an entry naming their files. A pattern with
 * nothing to say renders nothing; a pattern with something to say imports
 * it from web/lib/copy/.
 *
 * WHY THE COLOUR SELECTORS ARE REPEATED BELOW. Flat config REPLACES a
 * rule's options rather than merging them, so a second `no-restricted-syntax`
 * entry covering components/patterns/** would switch WO-01's
 * no-literal-colour rule OFF for exactly the newest files in the repository.
 * The primitives boundary avoided this by using a different rule; there is
 * no second rule that expresses "no rendered literal", so this block carries
 * both sets and `web/tests/copy/lint.test.ts` asserts the union is what the
 * resolved config for a real patterns file contains.
 */
const NO_INLINE_TEXT_MESSAGE =
  "User-facing text may not be written here. WO-12 acceptance criterion 1: " +
  "one copy module is the single edit site for every user-facing string, " +
  "because 03 §5.5's forbidden strings and 04 §9.1's honesty rules can only " +
  "be tested where the sentences are. Add the string to web/lib/copy/ " +
  "(errors.ts, run.ts or threads.ts) and import it. Non-rendered strings — " +
  "aria-label, title, class names, data attributes — are out of scope of " +
  "this rule.";

const TEXTUAL = "[A-Za-z]";

/**
 * Every child-slot shape, anchored at the element.
 *
 * The anchor is load-bearing: a JSX ATTRIBUTE value in braces is also a
 * `JSXExpressionContainer`, so an unanchored selector would flag
 * `data-open={open ? "true" : "false"}` — a non-rendered string, which is
 * explicitly out of scope. A container that is a direct child of a
 * `JSXElement` or `JSXFragment` is a child slot and nothing else.
 */
const CHILD_SLOT = [
  // `<p>{"Something went wrong."}</p>`
  `JSXExpressionContainer > Literal[value=/${TEXTUAL}/]`,
  `JSXExpressionContainer > TemplateLiteral > TemplateElement[value.raw=/${TEXTUAL}/]`,
  // ...and the three expressions a literal usually hides inside.
  `JSXExpressionContainer > ConditionalExpression > Literal[value=/${TEXTUAL}/]`,
  `JSXExpressionContainer > LogicalExpression > Literal[value=/${TEXTUAL}/]`,
  `JSXExpressionContainer > BinaryExpression > Literal[value=/${TEXTUAL}/]`,
];

const noInlineText = [
  // A text node in a JSX body: `<p>Something went wrong.</p>`. JSXText
  // occurs in no other position, so it needs no anchor.
  `JSXText[value=/${TEXTUAL}/]`,
  ...["JSXElement", "JSXFragment"].flatMap((parent) =>
    CHILD_SLOT.map((selector) => `${parent} > ${selector}`),
  ),
].map((selector) => ({ selector, message: NO_INLINE_TEXT_MESSAGE }));

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
  {
    /**
     * WO-12 criterion 1 — see NO_INLINE_TEXT_MESSAGE above for the whole
     * argument, including why the colour selectors are repeated here.
     *
     * tests/fixtures/copy-*.fixture.tsx are in scope for the same reason
     * WO-01's and WO-07's fixtures are: web/tests/copy/lint.test.ts lints a
     * real committed file that really fails, which is what proves the rule
     * fires rather than merely being configured. `npm run lint` walks only
     * app/ components/ lib/, so the failing fixture never breaks the
     * repository lint.
     */
    name: "copy/no-inline-text",
    files: [
      "components/patterns/**/*.{ts,tsx}",
      "components/features/**/*.{ts,tsx}",
      "tests/fixtures/copy-*.fixture.{ts,tsx}",
    ],
    rules: {
      "no-restricted-syntax": ["error", ...noLiteralColour, ...noInlineText],
    },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
