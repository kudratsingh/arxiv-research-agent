# 01 · Design references: what to borrow, and what not to

The owner named four references. Each one contributes **patterns**. None of
them contributes **assets**: no logos, mascots, icon sets, product names,
exact colours or trade dress. The composite is original.

## 1. Claude Code web app: the base layout (the owner's screenshot)

What the screenshot shows:
- **Left sidebar.**
  - A small header row: product name plus two icon toggles.
  - Primary rows with leading icons: New, Search, Artifacts, Scheduled, Customize, More.
  - A **"Recents"** section whose active row has a soft rounded highlight.
  - A thin divider and quiet footer.
- **Centre column.**
  - A slim top bar with a title and a ⌄ dropdown.
  - Icon buttons and a labelled primary action ("Share").
  - The content is a single calm reading column.
- **Bottom composer.** A **floating, rounded, bordered bar** inset from the
  column edges. It has a leading `+`, a placeholder "Type / for commands" and
  a trailing mic icon.
- **Right panel ("Plan").** A checklist. *Not adopted: the owner wants one
  sidebar.*
- **Tone.** Near-black neutral panels, 1px low-contrast borders, generous
  line height, large readable sans text, no heavy shadows.

What we take:

| Pattern | Our version |
|---|---|
| Sidebar header row with icon toggles | Mascot + "Research workspace" wordmark + icon buttons (collapse sidebar, theme) |
| Primary nav rows with icons | Today · Radar · Library · Interests · Sources & checks · Review |
| "Recents" list with rounded active highlight | **"Up next" queue**: the ordered papers, current row highlighted |
| Slim top bar with title + primary action | Breadcrumb `Today › 3 / 9` + paper short title + **Read & investigate** (primary red) |
| Floating rounded composer | **Control bar**: input "Search stored papers, or type / for commands", plus an action row |
| Calm single reading column | Focused paper column, max about 820px, centred |

## 2. Claude Code composer: the bottom control bar (owner: "nice design")

- Rounded 16px container with a 1px border and a slight raised surface. It
  floats with about 16px of margin from the column edges and the bottom.
- First row: the text input, with a leading `+` button and a trailing
  icon-button cluster.
- Second row (ours): **player-style controls**. See §3.
- Keyboard hints render as small mono `kbd` chips in muted ink.
- Pressing `/` from anywhere outside a text field focuses the input. This is
  a Claude Code / Slack habit.

## 3. Spotify: media-library feel

| Spotify pattern | Our version |
|---|---|
| "Your Library" sidebar with filter **chips** (Playlists / Artists …) and a dense list | Sidebar queue with chips: **Today · Saved · Notes** (Today route), view chips on Library |
| Numbered track list; the **playing track's number becomes an animated equalizer** in the accent colour | Queue rows numbered `01, 02…`. The **focused row's number becomes a red three-bar equalizer**: "now reading". Static under reduced motion. |
| Album art everywhere (big on the album page, small in the list, tiny in the now-playing bar) | **Generated cover tiles** per paper. Deterministic CSS pattern from a hash of `work_id`, with the source code and monogram. Large in the hero, small in the control bar. Optional 28px tiles in queue rows. |
| Album page header with a **colour wash from the artwork** fading into the page | A subtle **red gradient wash** at the top of the focused-paper stage |
| Big round **play** button in the accent colour | The primary **Read & investigate** action as the only filled red button on the stage, plus a round red "open" button in the control bar |
| **Now-playing bar**: art + title/artist (left) · ⏮ ⏯ ⏭ + progress (centre) · volume/queue (right) | Control bar action row: mini cover + title/source (left) · **⏮ prev · open · next ⏭** + queue progress `3 / 9` (centre) · **Save · Dismiss · Snooze · Undo** (right) |
| Heart/"liked" state in green | **Saved** state as a filled bookmark glyph in red, with the label "Saved" |
| Hover reveals play affordance on rows | Hover or focus reveals `↵ open` on queue rows |
| Rounded panels with 8px gaps on a black app background | Sidebar and stage as rounded panels (12px) separated by an 8px gutter on the canvas (desktop ≥1024px) |

Not taken: Spotify's green, its circular-logo brand, its fonts, the right
"Now playing" panel, heavy imagery, and autoplay.

## 4. VS Code / Codex: integrated, keyboard-first density

- **Activity cues and a status line.** One mono status strip that always shows
  `● Local workspace · Real source metadata · private server saves · generation off`
  (this exact text is test-pinned), plus the source-check summary and a
  `⌘K` hint.
- **Command palette.** `⌘K` / `Ctrl+K` opens a native `<dialog>` that lists
  navigation targets and the current screen's actions, with fuzzy filtering.
  It is lazy-loaded (see [04 §6](04-architecture.md#6-budgets)).
- **Shortcuts help.** `?` opens a cheat-sheet dialog.
- **Breadcrumbs and tabs feel.** The top bar reads like an editor tab:
  `workspace › today › 03 / 09`.
- **Mono for machine facts.** IDs, versions, counts, dates, kbd hints and
  section labels use the mono family. Prose uses the UI and report families.

## 5. "Cartoonish, like the Claude mascot"

The owner likes *having* a friendly mascot integrated into a serious tool. We
make our **own** character:
- **Folio**, a red bookmark-ribbon creature drawn on a 16×16 pixel grid.
  It has round eyes and a V-notch at the bottom that forms two little legs.
  Full spec in [02 §6](02-design-system.md#6-mascot-folio).
- It must not resemble Anthropic's mascot (no crab or creature silhouette
  borrowed, no orange) or any other brand's character.

## 6. Mood words for reviewers

*Crisp. Quiet. Confident. Keyboard-fast. Playful only at the edges.* The
reading surface is serious and the chrome has personality.
