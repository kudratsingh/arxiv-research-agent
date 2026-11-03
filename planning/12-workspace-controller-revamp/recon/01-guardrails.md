Every guardrail a workspace revamp has to pass is listed below, and all of them pass on HEAD 916f038 (`npm run lint` exits 0). The tightest constraint is **emitted CSS: 17,321 B measured against a 17,408 B ceiling, so 87 B of headroom across the whole app**. For the palette, the safest route is one fenced block appended to `app/tokens.css` that is scoped to the workspace root. I tested that block against the actual test suites and it passes with no test changes.

How I checked: I made a scratch copy of `web/` (its `node_modules` symlinked to the repo's), ran `next build --webpack` and `node scripts/route-budgets.mjs` there, and probed palette variants against the unit tests (`tokens`, `storybook`, `shell/layout`, `primitives/policy` and `fonts` suites; 189 tests). I linted synthetic files with the repo's own ESLint config. The repo is unmodified.

## (1) Hard rules, with file:line and how each fails

1. **No colour literals in TS/TSX (`eslint.config.mjs:18-33`, block at :152-166, scope `app/**`, `components/**`, `tests/fixtures/**`).** Any string or template containing `#` plus 3/4/6/8 hex digits, or `rgb(`/`rgba(`/`hsl(`/`hsla(`, raises a `no-restricted-syntax` error: "Literal colours are not allowed here". This covers `fill="#000"`, `bg-[#fff]` and `style={{color:"#.."}}`. Named colours, `oklch()` and `color-mix()` are not caught; I confirmed `fill="black"` passes lint.

2. **Repo-wide literal-colour scan (`tests/tokens.test.ts:709-754`).** It reads every `.ts/.tsx/.css/.mjs/.js/.svg` under `web/`, skipping `node_modules`, `.next`, `out`, `build` and `.git`, with the regexes at :718-719.
   - Only `app/tokens.css`, `app/icon.svg` and the `literal-colour` fixture are exempt (:729-733).
   - Comments are not stripped, so a hex inside a comment in `workspace.css`, `daily.css`, a mascot `.svg` or a new test file fails. The workaround for tests is to assemble the string (precedent: `tests/copy/lint.test.ts:137`).
   - I confirmed a hex in `workspace.css` fails "finds no literal colour…", and that `color:red; background:black; oklch(...)` passes (a loophole that goes against the intent stated at `tokens.css:4`).

3. **Token parity (`tokens.test.ts:276-292`).** The custom properties on `:root`, `@media (prefers-color-scheme: dark) :root`, `:root[data-theme="dark"]` and `:root[data-theme="light"]` must exactly equal `tokens.json`. Adding `--ws-accent` inside `:root` fails 3 tests (:277, :330, :538).

4. **Exactly one rule per theme selector chain (`tokens.test.ts:199-219`).** A second bare `:root { … }` rule makes the whole file fail at load: "expected exactly one rule for [:root] … found 2" (confirmed).

5. **23 colour roles per theme (`tokens.test.ts:294-300`) and no `success`/`warning` hue (:302-320).**

6. **Unique `--color-*` names in `tokens.css` must total exactly 23 (`tests/storybook.test.ts:123-133`).** The regex is `^\s*(--color-[a-z-]+):`, matched against the whole file, and each name must also appear in `.storybook/preview.css:32ff`. A new `--color-accent` anywhere, even in a scoped block, fails with "expected 24 to be 23" (confirmed). Use another prefix such as `--ws-*`.

7. **Contrast records (`tokens.test.ts:422-476`).** Every `tokens.json` `contrastChecks` fg/bg hex must exist in the root or dark-attribute block of `tokens.css`, and the ratio must recompute within 0.01. `declaredColours` reads only `ROOT` and `DARK_ATTRIBUTE` (:252-258). So pairs for a scoped palette cannot be added to `tokens.json`; that fails with "is not declared in the light theme". `regressionsFixed` (`tokens.json:127`) pins the light `ink-muted`, `sunken`, `surface` and `review-text` values to their exact hex.

8. **Tailwind mapping (`tokens.test.ts:511-563`).** Every `:root` property must reach `tailwind.config` through `lib/tokens.ts`.

9. **No `web/public/` directory (`tokens.test.ts:670-674`).** So there is no static mascot file. `app/icon.svg` must keep `viewBox="0 0 32 32"` (:662-668).

10. **Lint coverage of protected pages and config.**
    - `app/(workspace)/page.tsx` and `app/(workspace)/c/[id]/page.tsx` must lint clean (:852-873).
    - The colour block's text must keep `"no-restricted-syntax": ["error", ...noLiteralColour]` with no `ignores` (:810-819).
    - Flat config replaces rule options rather than merging them (`eslint.config.mjs:79-87`). A new `no-restricted-syntax` block for `components/workspace/**` must spread `...noLiteralColour`, as :253 does.

11. **Inline-text rule (`eslint.config.mjs:246-255`) covers only `components/patterns/**` and `components/features/**`.**
    - Checked with ESLint `--print-config` and `lintText`: `components/workspace` and `app/(live)` get only the 4 colour selectors, so inline JSX text is allowed there.
    - Moving controller pieces into patterns/features makes every rendered literal an error, and the strings must then live in `lib/copy/`.
    - `tests/copy/lint.test.ts:98-114` pins those globs and forbids `ignores`.
    - The copy tests (`forbidden.test.ts:90-98`, :485, :634) cover only `lib/copy/*` and modules reached from `app/(learn)`. No copy test reads `components/workspace` or `app/(live)`.

12. **Primitives boundary (`eslint.config.mjs:192-232`, `tests/primitives/boundary.test.tsx:26-38`, :146-149).** Primitives cannot import `@/lib/api*`, `@tanstack/react-query` or `msw`. Exactly 11 primitives with stories exist, so adding a story under `components/primitives/` fails "ships no story that is not one of the eleven's". Put new controller components in `components/workspace/`.

13. **Lint runs with `--max-warnings 0` (`package.json:16`).** Warnings therefore fail too: `react-hooks/exhaustive-deps`, `@typescript-eslint/no-unused-vars`, `@next/next/no-img-element`, `jsx-a11y/*`. The React Compiler rules are errors: `set-state-in-effect`, `set-state-in-render`, `refs`, `purity`, `immutability`, `static-components`, `use-memo`. For example, `useEffect(()=>setIndex(0),[queue])` for the prev/next state fails, as does reading `ref.current` during render.

14. **Focus outlines (`tests/primitives/policy.test.tsx:201-208`).** In every `.css` under `web/`, a rule with `outline: none|0` must also set `outline-width`, `outline-style`, `outline-color` or `box-shadow` in the same rule.

15. **Fonts (`tests/fonts.test.ts:212-239`, exemptions at :190-198).**
    - No `font-family:`, `fontFamily:` or `font-[` anywhere outside the exempt files, and no family names.
    - Use `font: 500 30px/1 var(--font-report)` (precedent `daily.css:59`) or the `font-ui`/`font-mono`/`font-report` utilities.
    - Exactly 3 families are expected (:48-70, :86-93), so a cartoon display face is effectively out.

16. **CSP (`lib/server/csp.ts:59-111`, pinned by `tests/csp.test.ts:94-120`).**
    - `style-src 'self'` forbids `<style>` elements, including inside SVG.
    - The only addition beyond the ratified policy is `style-src-attr 'unsafe-inline'`, and `'unsafe-inline'` may appear exactly once.
    - Also: `img-src 'self' data:`, `font-src 'self'`, and `script-src` nonce plus `'strict-dynamic'`.

17. **Exact route set (`tests/shell/routing.test.ts:62-84`).** Every page must sit under `(workspace)`, `(learn)`, `(daily)` or `(live)` (:92-102). Adding, removing or renaming any `/workspace/*` page fails.

18. **Budget rows (`tests/budgets.test.ts:610-641`, :643-693, :695-703).**
    - The row-id list is exact, the ceilings are pinned literals, and there are exactly 20 gated rows.
    - `scripts/route-budgets.mjs:209-214` throws if a budgeted route is missing from the build.
    - The script accepts no arguments and reads no environment (:9-16).

19. **Coverage is global, not per path (`vitest.config.mts:51-63`, :441-446).**
    - Thresholds: statements 98.15, branches 94.0, functions 91.8, lines 99.11. They are enforced only in CI (`npm run test -- --coverage`, `ci.yml:844-853`); plain `npm test` does not enforce them.
    - The recorded measurement (:434-436) is 4309/4386, 3238/3441, 1556/1690, 3630/3654. That leaves about 4 statements, 3 branches, 4 functions and 8 lines of slack.
    - Lines are the binding column: net new code needs about 99.1% line coverage.
    - I could not re-measure coverage: the Storybook project fails to load in my scratch copy (symlinked `node_modules`).

20. **Dependency audit (`tests/audit.test.ts:227-233`, :310-314).** Production advisories have no exception path, and `audit-exceptions.json` must stay `[]`. Any new npm package (icons, animation, mascot) must be clean at high severity.

21. **End-to-end tests in CI (`ci.yml:1120`, :1153-1158).**
    - `live-workspace-e2e/live.spec.ts` needs zero critical/serious axe violations, including colour contrast (:196-200, :601-606).
    - It relies on these names and selectors: navigation "Research workspace" (:98), "Skip to main content" (:217), `.workspace-activity` (:323-379), `.workspace-receipt` (:189), "Save question", "Mark read", "Pin this question", "Unpin saved item", "← Library".
    - `readiness.spec.ts:18` uses `.daily-item h3`.
    - `workspace-e2e/daily.spec.ts:72-75` and :132 run axe at WCAG 2 A/AA on the `(daily)` routes, which also load `daily.css`.

## (2) Giving the workspace a black/white/red palette in both themes

**Option A: change the global tokens.** Not recommended.
- Files to edit:
  - All four theme blocks in `app/tokens.css`: colours at :31-53, :197-219, :232-254 and :267-289. The two dark blocks must be identical (`tokens.test.ts:486-488`).
  - `docs/revamp/design/tokens.json` `color.light` (:15) and `color.dark` (:40). Values must match the CSS strings exactly, case included.
  - Every affected `contrastChecks` entry (:67-126), and `regressionsFixed` (:127-132) if `ink-muted`, `sunken`, `surface` or `review-text` change.
- `lib/tokens.ts` and Tailwind need no change if role names stay the same. A new role means also editing the "23" at `tokens.test.ts:296-297` and `storybook.test.ts:129`, plus `.storybook/preview.css` and `components/foundations/Colour.stories.tsx`.
- It re-skins the Evidence Workbench, learn and daily surfaces, which invalidates the visual/readme snapshots and the axe baselines.

**Option B: a scoped block in `tokens.css`.** Recommended. It is the only file allowed to hold hex values. Put it in its own fenced section after the reduced-motion block (:303-310), following the convention of the existing fence at :312, and update the header comment at :16-22. Shape:
```css
.workspace-app { color-scheme: light; --color-canvas:#FFFFFF; --color-ink:#000000; /* any of the 23 */ --ws-accent:#D70000; }
:root[data-theme="dark"] .workspace-app { color-scheme: dark; /* dark values */ }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .workspace-app { /* same dark values */ } }
```
- Tested: 189/189 pass with no changes to tests, `tokens.ts` or `tokens.json`. Redeclaring an existing `--font-*` token inside the scope also passed.
- Constraints:
  - Never add a second bare `:root{}`.
  - Never add properties to the four theme blocks.
  - Never introduce a new `--color-*` name; use `--ws-*`.
  - Keep the block after `:root`, because `tests/shell/layout.test.ts:67-71` and `tests/primitives/support/css.ts:103-110` take the first match.
- Because the 23 roles are redeclared inside the scope, Tailwind utilities, `SkipLink`/`ThemeToggle` and the focus ring (`--color-focus`) follow automatically.
- Caveats:
  - `body` (`globals.css` `bg-canvas`) and any portal sit outside the scope. `:root:has(.workspace-app)` would reach them; for dark it needs the `(0,3,0)` form `:root[data-theme="dark"]:has(...)`.
  - Nothing tests the scoped values' contrast except the e2e axe runs. Add a dedicated test, assembling the hex strings so the scan doesn't trip.
  - Contrast values I computed: `#D70000` on `#FFF` is 5.40, `#FFF` on `#D70000` is 5.40, `#FF4D4D` on `#000` is 6.42, `#000` on `#FF4D4D` is 6.42, and `#D70000` on `#F2F2F2` is 4.82.
- It costs CSS bytes: roughly 3×30 declarations against 87 B of headroom (see 4).

**Option C: remap existing tokens in `workspace.css` with `var()` and no hex.** For example `--color-primary: var(--color-critical-text)`. It passes every test, with precedent in `--ew-target-size`/`--ew-rail-width`. But it can't produce true black or white (dark canvas stays `#0E1A1E`, dark red is the salmon `#F2908A`), and it merges the accent with the `critical` status role (`lib/tokens.ts:183-189`).

## (3) Inline SVG mascot and `style={{}}`

- **Inline SVG with `fill="currentColor"`:** allowed, with precedent at `components/primitives/marks.tsx:41-155`. Presentation attributes are not covered by CSP.
- **Colour fills:** set them through `currentColor` plus a class `color: var(--…)`, or through `style={{fill:"var(--ws-accent)"}}`. Both lint clean (confirmed). I'd avoid `fill="var(--x)"` as an attribute: it lints clean, but nobody in the repo has verified browser support for it.
- **Banned in the mascot:**
  - Hex fills: fail ESLint and the scan.
  - A `<style>` inside the SVG, or styled-jsx: blocked by `style-src 'self'`.
  - A `.svg` file with colours, or anything in `public/`: fails rules 2 and 9.
  - A `data:` SVG with hex in CSS: fails the scan.
- Make it `aria-hidden`, and time any animation off `var(--duration-*)` so the reduced-motion collapse applies (`tokens.css:303-310`).
- **`style={{}}`:** allowed by CSP via `csp.ts:98` and by ESLint if there are no literal colours (sanctioned shape: `tests/fixtures/token-colour.fixture.tsx:15`). `fontFamily` inside it fails `fonts.test.ts:236`. Prefer classes: `csp.ts:96-97` records removing `style-src-attr` as a planned follow-up.

## (4) Budget headroom (fresh build at HEAD, gzip level 6)

| Row | Measured | Ceiling | Headroom |
|---|---|---|---|
| **All emitted CSS (global)** | **17,321** | **17,408** | **87 B** |
| `/workspace/today` | 157,032 | 169,984 | 12,952 |
| `/workspace/radar` | 155,497 | 169,984 | 14,487 |
| `/workspace/interests` | 162,655 | 169,984 | **7,329** |
| `/workspace/library` | 157,829 | 169,984 | 12,155 |
| `/workspace/items/[id]` | 162,472 | 169,984 | **7,512** |
| `/workspace/operations` | 153,632 | 169,984 | 16,352 |
| `/workspace/review` | 154,792 | 169,984 | 15,192 |
| Shared runtime | 133,759 | 139,264 | 5,505 |

The `(daily)` routes, which share `daily.css`, have 8,221 to 11,917 B of JS headroom.

- **What the CSS row holds:** `daily.css` emits about 3,415 B gz, `workspace.css` about 2,334 B gz, and Tailwind utilities plus `tokens.css` are in the 7,202 B bundle. Any new utility class or token block counts.
- **Where room can come from:** `DailyShell.tsx:6` still imports `daily.css`, so dropping the import from `Shell.tsx:7` saves nothing. Real room comes from rewriting or replacing `workspace.css`, roughly 2.4 KB gz available.
- **How to raise the CSS ceiling:**
  - Edit `budgets.json:272` and append a ratchet entry before :176 (`from` 17408, `measuredBytes`, a `why` over 80 characters).
  - Move `derived-total-first-load` (`:307`, = 192512 + CSS + 109568) and give it its own ratchet entry.
  - Update the `budgets.test.ts:668` and :677 literals, and state the reason in the PR body.
- **JS:** the `(live)/template.tsx` shell code is counted on all 7 routes, so a queue or controller in the shell eats from the tightest rows first (interests and items, about 7.3 KB).

The build and budget logs are in `/tmp/claude-0/-home-user-arxiv-research-agent/a2a832ec-056f-594b-8dc7-0ad1dc9cbee5/scratchpad/` (`build.log`, `budgets.log`, and `webcopy/budget-report.md`).