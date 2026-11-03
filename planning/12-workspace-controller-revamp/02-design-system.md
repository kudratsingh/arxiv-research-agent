# 02 · Design system: high-contrast black, white and red

Every value below is a **proposal the implementing agent may tune**, under
two conditions:
1. Every pair the UI actually uses must keep the contrast floors in §2.3,
   enforced by a unit test.
2. The *character* must survive: black and white, one red accent, crisp, and
   playful only at the edges.

## 1. Where the tokens live (mechanics)

- **Literal colours may appear only in `web/app/tokens.css`.** This is
  enforced by ESLint and by a repo-wide scan in `tests/tokens.test.ts:709-754`.
  The scan also reads comments.
- The palette is a **scoped block appended to the end of `tokens.css`**
  ("Option B" in [recon/01-guardrails.md](recon/01-guardrails.md) §2). It was
  tested green against the existing suites. The block:
  - **Redeclares the 23 existing `--color-*` roles** under `.workspace-app`.
    That way existing utilities, `SkipLink`, `ThemeToggle` and the focus ring
    follow automatically.
  - **Adds new `--ws-*` variables** for everything the old system has no role
    for.
- **Never:**
  - Add a second bare `:root {}`.
  - Add properties to the four existing theme blocks.
  - Introduce any new `--color-*` name. `storybook.test.ts` counts exactly 23.
  - Write `font-family`.
- **Selectors** (dark has two mechanisms, exactly like the global tokens):
  ```css
  /* ===== WORKSPACE CONTROLLER PALETTE (planning/12) — scoped, owns no :root ===== */
  .workspace-app { color-scheme: light; /* LIGHT values */ }
  :root[data-theme="dark"] .workspace-app { color-scheme: dark; /* DARK values */ }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) .workspace-app { color-scheme: dark; /* DARK values */ }
  }
  ```
- The page `body` sits outside `.workspace-app`. To paint the canvas behind
  overscroll, add `:root:has(.workspace-app) body { background: var(--ws-canvas-outer) }`
  in the workspace stylesheet. The `--ws-canvas-outer` value is declared in
  the same scoped block on `:root:has(.workspace-app)` variants, or just let
  `.workspace-app` be `min-height: 100dvh` and fill the viewport.

## 2. Colour

### 2.1 Role table

| Role (`--color-*` redeclared) | Dark | Light | Used for |
|---|---|---|---|
| canvas | `#0A0A0A` | `#F5F5F5` | App background, gutters between panels |
| surface | `#141414` | `#FFFFFF` | Sidebar panel, stage panel |
| sunken | `#050505` | `#EDEDED` | Inputs, code, wells |
| ink | `#FAFAFA` | `#0A0A0A` | Primary text |
| ink-muted | `#B3B3B3` | `#4D4D4D` | Secondary text, abstract metadata |
| ink-faint | `#8F8F8F` | `#666666` | Tertiary text, queue numbers, hints |
| ink-disabled | `#6B6B6B` | `#9E9E9E` | Disabled controls only |
| border-subtle | `#262626` | `#E3E3E3` | Hairlines, panel edges |
| border-strong | `#6B6B6B` | `#8A8A8A` | Input borders, outline buttons (≥3:1) |
| primary | `#FF4D4D` | `#D70015` | Links, primary fills, progress fill |
| primary-strong | `#FF7A7A` | `#A80010` | Hover/pressed primary |
| primary-on | `#0A0A0A` | `#FFFFFF` | Text and icons on a primary fill |
| focus | `#FAFAFA` | `#0A0A0A` | Focus ring. White or black, **never red**, so it stays distinct from the accent. |
| signature | `#FF4D4D` | `#D70015` | Current-row bar, brand mark, equalizer |
| signature-text | `#FF6B6B` | `#B00012` | Red text on surfaces (eyebrows, "now reading") |
| signature-on | `#0A0A0A` | `#FFFFFF` | Text on a signature fill |
| review | `#F5A524` | `#B26B00` | "Limited/partial" marks (amber) |
| review-text | `#F5B54A` | `#8A5300` | Amber text |
| review-surface | `#2A1F0A` | `#FFF4E0` | Amber notice background |
| critical | `#FF8A80` | `#B3261E` | Error marks |
| critical-text | `#FF8A80` | `#9E1F18` | Error text |
| critical-surface | `#2B1111` | `#FDECEA` | Error notice background |
| critical-on | `#0A0A0A` | `#FFFFFF` | Text on an error fill |

New `--ws-*` variables, declared in the same scoped block:

| Variable | Dark | Light | Purpose |
|---|---|---|---|
| `--ws-raised` | `#1C1C1C` | `#FFFFFF` | Control bar, dialogs, hovered rows |
| `--ws-hover` | `#1F1F1F` | `#F0F0F0` | Row and button hover fill |
| `--ws-accent-soft` | `#2A1012` | `#FDECEE` | **Current queue row**, selected chip fill |
| `--ws-accent-wash` | `rgba(255, 77, 77, 0.16)` | `rgba(215, 0, 21, 0.08)` | Top-of-stage gradient start (fades to transparent) |
| `--ws-shadow-bar` | `0 8px 32px rgba(0,0,0,.6)` | `0 8px 28px rgba(10,10,10,.12)` | Control bar and dialog elevation |
| `--ws-success` | `#4ADE80` | `#15803D` | Only the "source ok" dot. Never text, always paired with a label. |
| `--ws-mascot-body` | `#FF4D4D` | `#D70015` | Mascot fill |
| `--ws-mascot-shade` | `#B3001B` | `#8F000E` | Mascot arms, feet, edge shading |
| `--ws-mascot-highlight` | `#FF9A9A` | `#FF6B78` | Mascot shine pixels |
| `--ws-mascot-eye` | `#FFFFFF` | `#FFFFFF` | Eye whites |
| `--ws-mascot-ink` | `#0A0A0A` | `#0A0A0A` | Pupils and mouth |
| `--ws-cover-ink` | `#FAFAFA` | `#0A0A0A` | Cover-tile pattern ink (paired with accent) |
| `--ws-cover-ground` | `#0A0A0A` | `#FFFFFF` | Cover-tile ground |

> **Important:** check whether `tests/tokens.test.ts` treats a `--ws-success`
> green as a forbidden "success hue". The ban at `:302-320` is on *role names*
> in `tokens.json`. If it trips, drop the green and use `--color-ink` for the
> ok dot plus the word "ok".

### 2.2 Theme behaviour

- **Theme switching.** `ThemeToggle` (Light / Dark / System) is unchanged in
  behaviour. It writes `data-theme` on `<html>`, so the scoped selectors
  follow. Re-skin it via CSS inside `.workspace-app`. Keep its native radios;
  `daily.spec` and `tests/shell/themeToggle.test.tsx` check them.
- **Design priority.** Design dark first: it is the owner's screenshot theme
  and the IDE feel. Light must be equally finished: white panels on `#F5F5F5`
  with black ink and red.

### 2.3 Contrast floors (computed 2026-11-03; re-verify in a unit test)

| Pair | Dark | Light |
|---|---|---|
| ink / canvas · surface · raised | 18.97 · 17.65 · 16.33 | 18.16 · 19.80 · 19.80 |
| ink / accent-soft (current row) | 17.03 | 17.36 |
| ink-muted / canvas · surface · raised | 9.44 · 8.79 · 8.13 | 7.75 · 8.45 · 8.45 |
| ink-faint / canvas · surface · raised | 6.12 · 5.70 · 5.27 | 5.27 · 5.74 · 5.74 |
| primary text / canvas · surface · raised | 6.05 · 5.63 · 5.21 | 4.94 · 5.38 · 5.38 |
| primary text / accent-soft | 5.44 | 4.72 |
| signature-text / surface · accent-soft | 6.64 · 6.41 | 7.36 · 6.45 |
| primary-on / primary fill | 6.05 | 5.38 |
| border-strong / surface · canvas (non-text ≥3) | 3.46 · 3.72 | 3.45 · 3.17 |
| focus / canvas · surface | 18.97 · 17.65 | 18.16 · 19.80 |
| review-text / review-surface · surface | 8.92 · 10.17 | 5.81 · 6.33 |
| critical-text / critical-surface · surface | 7.72 · 8.07 | 6.90 · 7.89 |

The rules:
- **Text** is at least 4.5:1, or at least 3:1 at 24px+ or 18.66px+ bold.
- **UI marks** (borders that identify a control, focus rings, progress fill
  and track) are at least 3:1.
- The contrast test must **assemble the hex strings** (e.g. `"#" + "FF4D4D"`),
  because the literal scan reads test files too. Precedent:
  `tests/copy/lint.test.ts:137`.

### 2.4 The red problem: accent vs error

Red is the accent, so red cannot *also* be the only error signal. Rules:
1. **Accent red** marks the current item, the primary action, progress, the
   brand and the mascot.
2. **Errors** use `critical-*` (a lighter coral in dark, a deeper brick in
   light). They **always** carry three things:
   - a ⚠ icon
   - a word ("Unavailable", "Failed", "Couldn't save")
   - a bordered `critical-surface` box

   Never colour alone. This is already a house rule (see the section-rail
   note in `tokens.css`).
3. **Partial/limited** states use amber `review-*`.
4. **OK** uses ink and the word "ok", optionally with the green `--ws-success`
   dot.

## 3. Typography

Only the three self-hosted families exist, and `fonts.test.ts` pins exactly
three. **Never write `font-family`.** Use the `font:` shorthand with the
`var()` stack, for example `font: 700 34px/1.15 var(--font-ui)`, or the
`font-ui` / `font-mono` / `font-report` utilities. Minimum rendered size is
**12px** anywhere.

| Style | Spec | Where |
|---|---|---|
| Paper title (focus) | `700 clamp(26px, 2.6vw, 38px)/1.15 var(--font-ui)`, tracking `-0.02em` | Focused paper `h3` in `.daily-item` |
| Page title | `600 20px/28px var(--font-ui)` | `h1` "What changed." etc. (compact, in the stage header) |
| Section heading | `600 16px/24px var(--font-ui)` | `h2` inside stage and sidebar |
| Abstract / reading | `400 18px/1.7 var(--font-report)`, max-width `68ch` | Focused abstract, reader body |
| Body UI | `400 15px/22px var(--font-ui)` | Sidebar rows, buttons |
| Small UI | `400 13px/18px var(--font-ui)` | Secondary lines in rows |
| Eyebrow / label | `500 12px/16px var(--font-mono)`, uppercase, tracking `0.08em` | `PAPER · v2 · ABSTRACT`, sidebar section labels |
| Machine facts | `400 12–13px var(--font-mono)` | IDs, versions, counts, dates, status line, `kbd` |
| Brand wordmark | `700 15px/20px var(--font-ui)` | "Research workspace" next to the mascot |

## 4. Space, shape, elevation, motion

- **Spacing.** Use the existing 4px scale (`--space-*`). Rhythm: sidebar row
  padding 8×12, section gap 24, stage padding 32 (desktop) / 16 (mobile),
  gutter between panels 8.
- **Radius.** These are new `--ws-*` variables in the scoped block. They
  depart from the Workbench's 6px ceiling on purpose, because the owner asked
  for the Claude Code / Spotify look.

  | Variable | Value | Used for |
  |---|---|---|
  | `--ws-radius-sm` | 6px | Buttons, inputs, `kbd` |
  | `--ws-radius-md` | 10px | Rows, cards, cover tiles |
  | `--ws-radius-lg` | 14px | Panels |
  | `--ws-radius-xl` | 18px | Control bar, dialogs |
  | `--ws-radius-pill` | 999px | Chips, round buttons |

  First grep `tests/` for radius assertions scoped to workspace CSS. None were
  found in recon.
- **Elevation.**
  - Panels are flat: a 1px `border-subtle` on `canvas`.
  - Only the control bar, dialogs and the mobile drawer get `--ws-shadow-bar`.
- **Motion.** Use only the existing duration and easing tokens (`--duration-fast`
  120ms, `--duration-base` 160ms, `--duration-slow` 240ms, `--ease-*`), so the
  global reduced-motion collapse applies. Keyframe animations (equalizer,
  mascot blink and hop) must be **disabled** inside
  `@media (prefers-reduced-motion: reduce)`.

  | Element | Motion |
  |---|---|
  | Focus change (prev/next) | Stage content cross-fades and slides 8px over 160ms |
  | Queue row highlight | Moves with a 120ms background transition |
  | Equalizer | Three bars scale Y between 30% and 100%, 1.1s loop, staggered |
  | Mascot blink | Eyes scale Y to 0.1 for 140ms, about every 6s |
  | Mascot hop (busy) | Translate Y −1px, 400ms alternate |

## 5. Iconography

- Use one `Icon` component in `components/workspace/Icon.tsx`: inline SVG,
  `viewBox="0 0 20 20"`, `fill="none"`, `stroke="currentColor"`,
  `stroke-width="1.75"`, round caps and joins, `aria-hidden="true"`. Every
  icon button needs a text label (visible or `sr-only`).
- **Set (about 20 glyphs, keep it lean for the JS budget):**
  - Navigation: `today` (sunrise), `radar` (concentric arcs), `library`
    (books), `interests` (target), `sources` (refresh), `review` (check-square).
  - Player: `prev`, `next`.
  - Actions:
    - `open` (arrow ↗ into box)
    - `save` (bookmark outline) and `saved` (bookmark filled with `currentColor`)
    - `dismiss` (×)
    - `snooze` (moon / clock)
    - `undo`
  - Chrome: `search`, `command` (⌘), `sidebar` (panel toggle), `theme`
    (half circle), `menu`, `external` (↗), `warning` (⚠), `plus`.
- **Rule.** Draw them fresh: simple geometric strokes. Do not copy any icon
  library or brand glyph.

## 6. Mascot: "Jazzy"

Jazzy is an original red **bookmark-ribbon creature**: a rounded-top
rectangle body, two round eyes looking down and right (reading), a tiny
smile, arm nubs, and a bookmark **V-notch** cut into the bottom that forms
two legs.

**Grid** (16×16, `.` = transparent). Colour keys:
- `R` = `--ws-mascot-body`
- `D` = `--ws-mascot-shade`
- `H` = `--ws-mascot-highlight`
- `W` = `--ws-mascot-eye`
- `K` = `--ws-mascot-ink`

```
      x: 0123456789ABCDEF
row  0:  ................
row  1:  ...RRRRRRRRRR...
row  2:  ..RRHHRRRRRRRR..
row  3:  ..RRHRRRRRRRRR..
row  4:  ..RRWWRRRRWWRR..
row  5:  ..RRWKRRRRWKRR..
row  6:  ..RRWKRRRRWKRR..
row  7:  ..RRRRRRRRRRRR..
row  8:  .DRRRRRKKRRRRRD.
row  9:  .DRRRRRRRRRRRRD.
row 10:  ..RRRRRRRRRRRR..
row 11:  ..DRRRRRRRRRRD..
row 12:  ..RRRRR..RRRRR..
row 13:  ..RRRR....RRRR..
row 14:  ..RRR......RRR..
row 15:  ..DD........DD..
```

**Implementation** (`components/workspace/Mascot.tsx`):
- Keep the grid as a `const` string array.
- Build **one `<path d>` per colour key** at module load. Each pixel is
  `M{x} {y}h1v1h-1z`, giving five paths.
- `<svg viewBox="0 0 16 16" shape-rendering="crispEdges" aria-hidden="true">`.
- Colour each path through a class whose CSS sets `fill: var(--ws-mascot-*)`.
  No hex anywhere. **No `<style>` element**, because CSP `style-src 'self'`
  blocks it.
- **Moods** via `data-mood`:

  | Mood | Behaviour | Where |
  |---|---|---|
  | `idle` | Blink | Brand |
  | `busy` | Hop; a small "…" bubble beside it | Source check running, saving |
  | `sleepy` | Eye groups hidden; a "closed eyes" path (row 5: `K` at x4–5 and x10–11) shown | Empty states |
  | `alert` | Pupils centred and no blink | Service unavailable; pair with the error box, never alone |

- **Sizes:**
  - 20px in the mobile top bar
  - 28px in the sidebar brand
  - 72px in empty states, with a speech-bubble line such as "Nothing new
    matched this reading window."

  The speech-bubble text *is* the existing empty-state copy, so tests keep
  passing.
- **Do not:** name, shape or colour it after any existing mascot, or add a
  separate `.svg` file (no `web/public/`; the scan forbids colour literals in
  `.svg`).

## 7. Cover tiles (Spotify album-art idea)

`components/workspace/CoverTile.tsx`. Deterministic, CSS-only and cheap.

- **Hash.** FNV-1a 32-bit of `work_id`, which gives `h`. Then:

  | Attribute | Value |
  |---|---|
  | `data-pattern` | `h % 6`: `0` diagonal stripes, `1` dot grid, `2` concentric rings, `3` pixel checker, `4` bar code / spectrogram, `5` quarter-circle |
  | `data-turn` | `(h >>> 3) % 4`, rotated 0/90/180/270 via classes |
  | `data-invert` | `(h >>> 5) % 2`: red-on-black or black-on-red (light: red-on-white or white-on-red) |

- **Content.** In mono 12px: the source short code, for example `cs.LG` from
  the source id or category, or `BLOG`. Bottom-left, in bold UI 28–40px: a
  **two-letter monogram** from the first two significant title words.
  `aria-hidden="true"`, because it is decorative and the title is adjacent.
- **Sizes:** 168px (stage hero, desktop) · 96px (stage hero, mobile) · 44px
  (control bar) · 28px (queue rows, optional; drop it if the CSS budget is
  tight).
- **Implementation.** Patterns are `repeating-linear-gradient`,
  `radial-gradient` and `repeating-radial-gradient` built only from
  `var(--ws-cover-ink)`, `var(--ws-cover-ground)` and `var(--color-signature)`.
  No inline `style` colours.

## 8. Component specs

States for every interactive element:
- `:hover` fills `--ws-hover`.
- `:active` darkens or lightens by one step.
- `:focus-visible` gets a 2px `--color-focus` outline with a 2px offset.
  `primitives/policy.test.tsx` requires a replacement whenever `outline: none`
  is used.
- `:disabled` / `[aria-disabled]` uses `ink-disabled` and `cursor: not-allowed`.
- `[aria-busy=true]` shows the mascot hop or a 3-dot pulse.
- `[aria-current]` / `[aria-pressed=true]` gets the accent-soft fill plus a
  3px left bar in `signature`, or a filled chip.

| Component | Anatomy and behaviour |
|---|---|
| **Sidebar panel** | `surface` panel, `radius-lg`, full height minus gutters, own scroll (`overflow-y: auto`, `overscroll-behavior: contain`). Sections are separated by 24px with mono uppercase labels. Collapsible on desktop to a 64px icon rail (persist per viewer in `localStorage` under try/catch, key `workspace-sidebar`). |
| **Nav row** | 36px tall, icon 20px + label, `radius-md`. Current route: accent-soft fill + 3px signature bar + 600 weight. Optional right-aligned `kbd` (`G T` etc.) on hover/focus. |
| **Queue row ("Up next")** | `<button>` (not a link, not an `<article>`) in an `<ol>`. Columns: `02` number (mono, faint), title (2-line clamp, 14px, ink), sub-line (source · access · status glyph, 12px muted). Focused row: accent-soft fill, signature bar, the **equalizer replaces the number**, `aria-current="true"`. Accessible name: **"Show paper 2 of 9: ‹title›"**. Never the bare title (see [07](07-test-impact.md) §2). |
| **Chips** | Pills, 28px, 13px text. Selected: ink fill with canvas text (dark: white pill with black text; light: black with white). Use real `<button aria-pressed>` or radio semantics. |
| **Segmented control** (reading time 5 / 15 / 45) | Pill group. Selected is a primary fill. The existing `aria-pressed` buttons stay. |
| **Buttons** | *Primary*: red fill, primary-on text, `radius-pill` in the bar, `radius-sm` elsewhere. *Secondary*: `border-strong` outline. *Ghost/icon*: transparent with hover fill. *Text*: underline on hover. Minimum target 32px (44px on coarse pointers). |
| **Kbd** | Mono 12px, 1px `border-subtle`, `radius-sm`, padding 1×5, faint text. |
| **Status line** | Mono 12px in the stage top bar. Contents: `●` dot · **`Local workspace`** · the pinned text **`Real source metadata · private server saves · generation off`** · source summary `5/5 sources` · `⌘K`. Visible at every width (wraps on mobile). |
| **Focus paper** | See [03 §3](03-screens-and-flows.md#3-today-the-focused-paper). |
| **Control bar** | See [03 §2.4](03-screens-and-flows.md#24-the-control-bar). |
| **Progress** | 4px track (`border-subtle`) with a `primary` fill at `index / count`. `role="progressbar"` with `aria-valuenow`, `aria-valuemax` and `aria-valuetext="Paper 3 of 9"`. |
| **Notices** | Inline boxes: amber for limited, coral for errors, both with icon + word. The page's single polite `role="status"` region (`Common.tsx` `Message`) stays the only live region. |
| **Empty state** | Mascot 72px (`sleepy`) + heading (existing copy, verbatim) + one-line help + one action. |
| **Dialogs** (palette, shortcuts) | Native `<dialog>` with `showModal()`, `raised` surface, `radius-xl`, `shadow-bar`. Esc closes. Focus returns to the invoker. Max width 640px. |
| **Mobile drawer** | A sheet from the left (or bottom) with a scrim. It holds the sidebar's queue and controls. Opened by a "Queue & controls" button. Esc or the scrim closes it. Focus is trapped while open. |
