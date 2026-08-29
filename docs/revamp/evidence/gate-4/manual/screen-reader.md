# Screen-reader sessions — **NOT YET EXECUTED — requires a human operator**

> **Status: PROTOCOL ONLY. This file contains no results.**
> Every transcription block below is blank and must stay blank until a person
> has run the session and pasted what they actually heard.
> [WO-27](../../../06-WORK-ORDERS.md#wo-27--accessibility-hardening-and-manual-evidence)
> criterion 3 is **not** satisfied by this file, and Gate 4 is blocked on it.

Produced by WO-27, criterion 3:

> `screen-reader.md` transcribes VoiceOver + Safari (macOS and iOS) and NVDA +
> Firefox for the plan-review decision, a reconnect announcement, and a
> terminal outcome.

---

## 0. Why this file is a protocol and not a transcript

WO-27 was executed by an automated agent on macOS. Two facts follow from that
and neither is negotiable:

1. **NVDA does not run on macOS at all.** It is a Windows application. There
   is no emulation, no headless mode and no CI runner in this project that
   could produce an NVDA session.
2. **A VoiceOver transcript cannot be synthesised.** VoiceOver's speech is
   produced by the platform from the accessibility tree plus VoiceOver's own
   verbosity settings, punctuation rules, hint timing and rotor state. An
   agent can read the accessibility tree — `web/e2e/keyboard.spec.ts` does,
   through Playwright's ARIA snapshot — but the tree is the *input* to the
   screen reader, not its output. Writing out what VoiceOver "would have
   said" would be a fabrication in the shape of evidence, and the one thing
   an evidence pack must never contain is a measurement nobody took.

[`04-ARCHITECTURE.md` §7.4](../../../04-ARCHITECTURE.md#74-axe-in-ci) already
says where the line is: "Automation cannot establish keyboard order, focus
restoration, announcement quality, or screen-reader comprehension." WO-27
moved the first two across that line — they are observable, and
[`keyboard.md`](keyboard.md) observes them with a scripted keyboard and says
so. The second two stay on this side of it. This file is what a human needs
in order to close them, written so that running it is mechanical.

**What is already known and does not need re-establishing here.** The
accessible names, roles, states and live-region structure are asserted by
machine: `web/e2e/keyboard.spec.ts` (focus order and restoration),
`web/e2e/motion.spec.ts` (live-region change counts under a 40-frame burst),
`web/e2e/axe-matrix.spec.ts` (the full state × theme × width sweep), and the
unit suite's copy and ARIA tests. What no machine here has established is
whether a person listening to the result **knows what happened and what to do
next**. That is the whole question below.

---

## 1. Environments to cover

Three sessions. Each is a separate run of the same three scenarios.

| # | Screen reader | Browser | Platform | Notes for the operator |
|---|---|---|---|---|
| A | VoiceOver | Safari | macOS 14 or later | `Cmd+F5` toggles VO. Use the default verbosity; do not raise it for the session. |
| B | VoiceOver | Safari | iOS 17 or later, real device | Triple-click the side button, or Settings → Accessibility → VoiceOver. Portrait, default text size. |
| C | NVDA (2024.1 or later) | Firefox (current ESR or stable) | Windows 10 or 11 | Speech viewer on (`NVDA+N` → Tools → Speech Viewer) so the session can be copied rather than typed from memory. |

**Record for each session, before scenario 1:** the exact reader version,
browser version, OS version, and the date. A transcript without them cannot
be reproduced or compared later.

### How to reach the states

Bring up the seeded stack the browser tier already uses — the fixtures are the
same ones every other piece of Gate 4 evidence was taken against:

```
cd web
npm run e2e:stack:up
npm run e2e:stack:seed
# the base URL it prints, e.g. http://127.0.0.1:13210
```

`web/e2e/fixtures/seed.sh` writes only `baseline-*` rows and never calls
`POST /research`, so nothing in this protocol can start a billable run.

| Scenario | URL |
|---|---|
| 1. Plan review | `/c/baseline-populated?job=baseline-plan-review` |
| 2. Reconnect | `/c/baseline-populated?job=baseline-running`, then see §4 |
| 3. Terminal outcome | `/c/baseline-populated?job=baseline-cancelled` and `?job=baseline-failed-partial` |

---

## 2. How to transcribe

- **Verbatim, including the parts that sound wrong.** If VoiceOver says
  "group" four times before it reaches the button, that is the finding.
- **One line per utterance**, in the order heard. Use `⏎` to mark where you
  pressed a key and `»` to mark a self-voicing announcement that arrived
  without a keypress (a live region firing).
- **Silence is data.** Write `(nothing announced)` where you expected speech
  and got none. A live region that never fires is the most common defect in
  this class and it leaves no trace anywhere else.
- **Do not clean up the punctuation.** "Waiting for your review. The run is
  paused and not spending." and "Waiting for your review the run is paused and
  not spending" are different results.
- **Note the rotor / elements-list contents** where the scenario asks for it.
  Heading and landmark navigation is how most readers actually move.

---

## 3. Scenario 1 — the plan-review decision

**What the user is trying to do.** Understand that a run is paused waiting for
them, read the plan, and either approve it or cancel the run — without ever
being unsure whether money is being spent.

**Why this scenario.** It is the only place in the product where a **decision**
is required before anything expensive happens
([`03` §5.6](../../../03-DESIGN-BRIEF.md)), and the surface carries three
things that are hard to hear well at once: a status badge, two arrays of
editable text, and a pair of decision buttons one of which is destructive.

### Steps

1. Load `/c/baseline-populated?job=baseline-plan-review`.
2. Navigate by **landmark** to `main`. Record everything spoken on arrival.
3. Navigate by **heading** through the page. Record the heading list.
4. Move to the plan region and read it linearly to the end (VO: `VO+A`; NVDA:
   `NVDA+DownArrow`). Record the whole reading.
5. Tab to the first sub-question field. Record what is announced: label, value,
   the character counter, and whether the counter is announced on entry only or
   on every keystroke.
6. Tab to `Remove sub-question 1`. Record the name exactly.
7. Activate it. Record **where focus went and what was announced there**.
8. Tab to `Approve plan`. Record the name **and any description** — the
   surface has a disclosure sentence about billing that is wired as
   `aria-describedby`.
9. Tab to `Cancel this run`. Record the name and description ("Nothing will be
   searched.").
10. Do **not** activate either. Reload the page instead.

### What a pass sounds like

- On arrival at the plan region the reader hears, in some order: that this is
  the plan, that it is **waiting for the user's review**, and that **nothing
  has been searched yet**. If the listener could not answer "is it spending
  money right now?" from what they heard, that is a fail regardless of what
  the visual surface says.
- Each remove button is announced with its **index** — "Remove sub-question 2",
  never three buttons all called "Remove".
- After a removal, focus lands on a field the reader can identify, and the
  reader hears enough to know the list changed. (The scripted walk confirms
  focus MOVES to `Sub-question 2` and to `Add sub-question` when the list
  empties; what it cannot confirm is that the listener knows a row is gone.)
- `Approve plan` is announced together with the billing sentence, not before
  or instead of it.
- `Cancel this run` is unambiguous about being destructive.

### Transcription — session A (VoiceOver + Safari, macOS)

```
reader version:
browser version:
OS version:
date:

(transcript)
```

### Transcription — session B (VoiceOver + Safari, iOS)

```
reader version:
browser version:
OS version:
device:
date:

(transcript)
```

### Transcription — session C (NVDA + Firefox)

```
reader version:
browser version:
OS version:
date:

(transcript)
```

### Operator's verdict

| Question | A | B | C |
|---|---|---|---|
| Was it clear a decision was required of the user? | | | |
| Was it clear nothing had been spent or searched yet? | | | |
| Were the remove buttons distinguishable from each other? | | | |
| After a removal, was it clear what had happened? | | | |
| Was the billing consequence of `Approve plan` heard? | | | |

---

## 4. Scenario 2 — a reconnect announcement

**What the user is trying to do.** Stay oriented while a live run's connection
drops and is re-established, without being told about it fifty times.

**Why this scenario.** This is the single hardest thing in the product to get
right for a listener, and it is the one
[`03` §7.3](../../../03-DESIGN-BRIEF.md) constrains most tightly: exactly two
live regions product-wide, one `role="status"` for material transitions and
one `role="alert"` for user-triggered failures, with the diagnostics
`role="log"` collapsed by default so routine frames are never announced.
`web/e2e/motion.spec.ts` proves the *count* — the status region changed a
small number of times over a 40-frame burst — but a count is not a sentence,
and "the region changed twice" says nothing about whether the two things it
said made sense in sequence.

### Steps

1. Load `/c/baseline-populated?job=baseline-running` and leave the page
   focused. Wait for the run panel.
2. Read the trace spine linearly. Record it.
3. **Interrupt the connection.** Any of these produces a real reconnect; note
   which you used:
   - macOS/Windows: turn Wi-Fi off for ~10 s, then on.
   - Or: browser devtools → Network → Offline, wait ~10 s, then Online.
   - Or, closest to the harness: with the stack up, `docker restart
     arxiv-wo21-app` (or whichever container name your overlay set).
4. Record **everything spoken without a keypress** from the moment the
   connection drops until 30 s after it returns. Mark each with `»`.
5. Now navigate deliberately to the status line and read it. Record it.
6. Expand the **Technical events** disclosure. Record what is announced on
   expansion, and then whether frames are announced as they arrive while it
   is open.
7. Collapse it again and wait 30 s. Record whether anything is still being
   announced.

### What a pass sounds like

- The drop and the recovery are announced **once each**, as sentences a person
  can act on, not as raw event names.
- Nothing is announced per frame while the diagnostics disclosure is
  **collapsed**. This is the specific claim
  [`03` §7.3](../../../03-DESIGN-BRIEF.md) makes and the one most likely to be
  false in practice.
- The checkpoint count and the run's age are **not** announced on every
  change — they live outside the `role="status"` region deliberately
  (`data-spine-part="detail"`).
- Nothing announces "error" for a reconnect the browser handled on its own.
  A retry is not a failure.
- After collapsing the disclosure, the page goes quiet.

### Transcription — session A / B / C

```
session A (VoiceOver + Safari, macOS) — interruption method:

(transcript)
```

```
session B (VoiceOver + Safari, iOS) — interruption method:

(transcript)
```

```
session C (NVDA + Firefox) — interruption method:

(transcript)
```

### Operator's verdict

| Question | A | B | C |
|---|---|---|---|
| How many times was the drop announced? | | | |
| How many times was the recovery announced? | | | |
| Was anything announced per frame while collapsed? | | | |
| Did anything call a browser-handled retry an error? | | | |
| Did the page go quiet when the disclosure was collapsed? | | | |

---

## 5. Scenario 3 — a terminal outcome

**What the user is trying to do.** Find out how a run ended, and whether there
is anything to read or export.

**Why this scenario.** [`03` §3.4](../../../03-DESIGN-BRIEF.md) puts the
status **word** first and the colour last; a listener gets only the word. Two
terminal outcomes are used because they are the two that are easiest to
confuse by ear: a run the user cancelled, and a run that failed but still
produced something worth reading.

### Steps — 3a, cancelled

1. Load `/c/baseline-populated?job=baseline-cancelled`.
2. Read the trace spine linearly. Record it.
3. Navigate by heading. Record the list.
4. Record whether anything says the run was **cancelled** as opposed to
   failed, and whether anything implies a briefing exists.

### Steps — 3b, failed with a partial briefing

1. Load `/c/baseline-populated?job=baseline-failed-partial`.
2. Read the page linearly from the top of `main`. Record it.
3. Record, specifically, the order in which the listener hears: that the run
   failed, and that a partial briefing is present anyway.
4. Navigate to the briefing and read one heading and one table. Record how the
   table is announced — the tables are wrapped in labelled, focusable scroll
   regions ("Table 1 in this briefing").
5. Find the export control. Record its name and what happens on activation.

### What a pass sounds like

- "Cancelled" and "Failed" are heard as different words, not inferred from
  tone or position.
- On 3b the listener hears the failure **and** that something readable
  survived it — in that order, and without having to hunt.
- The briefing's table is reachable and announced as a table with its caption,
  and the listener can tell it is scrollable.
- The export control's name says what it exports.

### Transcription — session A / B / C

```
session A (VoiceOver + Safari, macOS)

3a (cancelled):

3b (failed-partial):
```

```
session B (VoiceOver + Safari, iOS)

3a (cancelled):

3b (failed-partial):
```

```
session C (NVDA + Firefox)

3a (cancelled):

3b (failed-partial):
```

### Operator's verdict

| Question | A | B | C |
|---|---|---|---|
| Were "cancelled" and "failed" distinguishable by word alone? | | | |
| On 3b, was the surviving briefing discoverable? | | | |
| Was the table announced as a table, with its caption? | | | |
| Did the export control say what it exports? | | | |

---

## 6. Known structural findings to check by ear

These were found by the scripted passes and are **not** defects axe or the
keyboard walk can settle. They are listed here because a screen-reader session
is the instrument that decides them.

1. **Two `<h1>` elements on a populated thread.** The page's `h1` is the
   thread title; the briefing's Markdown `#` renders as a second `h1` inside a
   `region` whose own heading is an `h2`, so the document goes h1 → h2 → h1 →
   h2. This is what [`03` §5](../../../03-DESIGN-BRIEF.md) specifies — the type
   scale has a `report-h1` step and the section rail is defined as "derived
   from the report's own `h2`/`h3` nodes" — and axe reports nothing, because
   `heading-order` only flags *increases* of more than one. **Record the
   heading list the rotor / elements list actually offers** in scenario 3b and
   say whether the nesting is confusing. If it is, the fix reopens WO-18 and is
   a design ruling, not a bug fix.
2. **The briefing's own top-level heading is absent from the section rail.**
   `readHeadings()` collects `h2, h3` only, so a reader navigating by the
   Sections nav never reaches the briefing's title. Same owner, same question.
3. **`ExportDisclosure` emits a second `role="alert"`** for the 409 "nothing to
   export" refusal, outside `StatusBanner`. A thread showing both an export
   refusal and a failure banner has two alerts. Not reachable from the seeded
   fixtures; worth a note if the operator ever hears two.

---

## 7. What to do with the results

- If every verdict cell is a pass: replace the header of this file with a
  dated **EXECUTED** block naming the operator, and WO-27 criterion 3 is met.
- If any cell is a fail: the fix belongs to the owning work order (WO-17 for
  the plan editor, WO-16 for diagnostics, WO-10 for the reconnect narration,
  WO-18 for the report), and WO-27 re-runs the affected scenario afterwards.
- Either way, record the outcome in the Gate 4
  [`README.md`](../README.md) and in `known-gaps.md` if anything is left open.
