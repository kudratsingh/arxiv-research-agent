/**
 * WO-13 — `QueryComposer`, criterion by criterion.
 *
 * CRITERION 1 IS ASSERTED AGAINST THE BRIEF ITSELF, not against a copy of
 * it typed here. `03-DESIGN-BRIEF.md` §1.4 prints the landing surface as a
 * fenced block of `[slot] value` rows and says "Verbatim"; this file parses
 * that block out of the Markdown and compares it to the rendered DOM, the
 * same way `web/tests/copy/errorTypeDrift.test.ts` re-derives the
 * `error_type` list from the Python sources. A test that restated the
 * strings would only prove the strings match themselves.
 *
 * The other nine criteria are behaviour, and the two that cost money are
 * the ones to read first: criterion 5 (exactly one `onSubmit` per intent)
 * and criterion 6 (no automatic retry on any path). `POST /research` has no
 * idempotency key (`routes.py:179-197`), so both are about not being billed
 * twice.
 *
 * WHAT IS NOT HERE. The Playwright interceptor that counts real
 * `POST /api/research` calls is WO-21's (criterion 5 says so), as is the
 * committed bounding-box spec for criterion 3 — jsdom has no layout, so
 * what is assertable here is order and structure, and the measured box is
 * in the PR body.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";

import * as stories from "@/components/features/QueryComposer.stories";
import { QueryComposer } from "@/components/features/QueryComposer";
import { VISUALLY_HIDDEN_CLASS } from "@/components/primitives/VisuallyHidden";
import { COMPOSER } from "@/lib/copy/composer";
import { FAILURE_COPY } from "@/lib/copy/errors";
import { LANDING, MAX_QUERY_LEN, queryCounter, queryOverLimit } from "@/lib/copy/run";
import type { ApiFailure } from "@/lib/api";

import { fireEvent, render, screen, user, within } from "../support/render";

// ---------------------------------------------------------------------------
// 03 §1.4, parsed out of the brief.
// ---------------------------------------------------------------------------

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const BRIEF = path.join(REPO_ROOT, "docs", "revamp", "03-DESIGN-BRIEF.md");

/**
 * The `[slot] value` rows of §1.4's fenced block.
 *
 * A row continues onto the following indented lines, which is how the
 * brief wraps the placeholder and the disclosure; a blank line ends it.
 * Joining with a single space is what the brief's own layout means — the
 * wrap is typography, not content.
 */
function parseLandingBlock(markdown: string): Record<string, string> {
  const section = markdown.slice(markdown.indexOf("### 1.4 Landing copy"));
  const fence = /```text\n([\s\S]*?)```/.exec(section);
  if (fence === null) throw new Error("03 §1.4: no fenced text block found");

  const slots: Record<string, string> = {};
  let current: string | null = null;
  for (const line of (fence[1] as string).split("\n")) {
    const start = /^\[(\w+)\]\s+(.*)$/.exec(line);
    if (start !== null) {
      current = start[1] as string;
      slots[current] = (start[2] as string).trim();
      continue;
    }
    if (line.trim() === "") {
      current = null;
      continue;
    }
    if (current !== null) slots[current] = `${slots[current]} ${line.trim()}`;
  }
  return slots;
}

const SLOTS = parseLandingBlock(readFileSync(BRIEF, "utf8"));

/** The process strip, split on the brief's own separator. */
const PROCESS = (SLOTS["process"] as string).split(/\s*·\s*/);

// ---------------------------------------------------------------------------
// Fixtures.
// ---------------------------------------------------------------------------

const QUESTION = "How is faithfulness measured in retrieval-augmented generation?";

/**
 * The field H12 forbids, spelled from parts.
 *
 * `web/tests/api.test.ts` does the same and for the same reason: its
 * containment scan fails any file under app/, components/, lib/ or tests/
 * that contains the literal outside lib/api, and a test that wrote it out
 * would be the first thing that scan found.
 */
const BYPASS_FIELD = ["hitl", "bypass"].join("_");

const RATE_LIMITED: ApiFailure = {
  kind: "rate_limited",
  status: 429,
  retryAfterSec: 900,
  message: "",
  raw: null,
};

const UNREACHABLE: ApiFailure = {
  kind: "upstream_unavailable",
  status: 502,
  message: "",
  raw: null,
};

function field(): HTMLTextAreaElement {
  return screen.getByLabelText(LANDING.questionLabel) as HTMLTextAreaElement;
}

function submitButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: new RegExp(`^(${LANDING.submit}|${LANDING.submitPending})$`),
  }) as HTMLButtonElement;
}

function noop(): void {
  /* a story and several assertions need a submit handler that does nothing */
}

// ---------------------------------------------------------------------------
// Criterion 1 — the landing copy, string for string.
// ---------------------------------------------------------------------------

describe("criterion 1 — 03 §1.4 verbatim", () => {
  it("parsed a block with every slot the brief prints", () => {
    expect(Object.keys(SLOTS).sort()).toEqual([
      "button",
      "counter",
      "disclosure",
      "eyebrow",
      "h1",
      "label",
      "process",
      "textarea",
    ]);
  });

  it("the copy dictionary carries the brief's strings unchanged", () => {
    expect(LANDING.eyebrow).toBe(SLOTS["eyebrow"]);
    expect(LANDING.heading).toBe(SLOTS["h1"]);
    expect(LANDING.questionLabel).toBe(SLOTS["label"]);
    expect(LANDING.questionPlaceholder).toBe(SLOTS["textarea"]);
    expect(LANDING.disclosure).toBe(SLOTS["disclosure"]);
    expect(LANDING.submit).toBe(SLOTS["button"]);
    expect(queryCounter(0)).toBe(SLOTS["counter"]);
    expect([...LANDING.process]).toEqual(PROCESS);
  });

  it("renders every one of them", () => {
    render(<QueryComposer onSubmit={noop} />);

    expect(screen.getByText(SLOTS["eyebrow"] as string)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      SLOTS["h1"] as string,
    );
    expect(field()).toHaveAttribute("placeholder", SLOTS["textarea"] as string);
    expect(screen.getByText(SLOTS["counter"] as string)).toBeInTheDocument();
    expect(screen.getByText(SLOTS["disclosure"] as string)).toBeInTheDocument();
    expect(submitButton()).toHaveTextContent(SLOTS["button"] as string);

    const strip = screen.getByRole("list", { name: COMPOSER.processLabel });
    expect(
      within(strip)
        .getAllByRole("listitem")
        .map((item) => item.textContent?.replace(/·/g, "").trim()),
    ).toEqual(PROCESS);
  });

  it("the disclosure is persistent body copy, immediately above the button", () => {
    render(<QueryComposer onSubmit={noop} />);
    const disclosure = screen.getByText(LANDING.disclosure);

    // Body copy: a paragraph, on screen, from the first render.
    expect(disclosure.tagName).toBe("P");
    expect(disclosure).toBeVisible();
    expect(disclosure).not.toHaveAttribute("hidden");
    expect(disclosure).not.toHaveAttribute("aria-hidden");

    // Immediately above the button — its next element sibling, with
    // nothing rendered between the two.
    expect(disclosure.nextElementSibling).toBe(submitButton());
  });

  it("is not a tooltip, a title, or revealed on hover", async () => {
    render(<QueryComposer onSubmit={noop} />);

    // Nothing in the tree hides the sentence behind a `title` or a
    // tooltip role — both would put it one hover away from a mouse user
    // and out of reach of everyone else.
    for (const node of Array.from(document.querySelectorAll("[title]"))) {
      expect(node.getAttribute("title")).not.toContain(LANDING.disclosure);
    }
    expect(screen.queryByRole("tooltip")).toBeNull();

    // And it is already there before anything is hovered.
    const before = screen.getByText(LANDING.disclosure);
    await user().hover(submitButton());
    expect(screen.getByText(LANDING.disclosure)).toBe(before);
  });

  it("puts the disclosure in the submit button's accessible description", () => {
    render(<QueryComposer onSubmit={noop} />);
    const described = submitButton().getAttribute("aria-describedby") ?? "";
    expect(described.split(" ")).toContain(
      screen.getByText(LANDING.disclosure).id,
    );
  });
});

// ---------------------------------------------------------------------------
// Criterion 2 — the counter, and the bound.
// ---------------------------------------------------------------------------

describe("criterion 2 — the counter and MAX_QUERY_LEN", () => {
  it("the bound is the backend's own (src/api/schemas.py:17)", () => {
    const schemas = readFileSync(
      path.join(REPO_ROOT, "src", "api", "schemas.py"),
      "utf8",
    );
    // `8_000` in the source: Python's digit separator, stripped here.
    const declared = /^MAX_QUERY_LEN\s*=\s*([\d_]+)/m.exec(schemas);
    expect(declared).not.toBeNull();
    const bound = ((declared as RegExpExecArray)[1] as string).replace(/_/g, "");
    expect(Number(bound)).toBe(MAX_QUERY_LEN);
  });

  it("is visible from zero characters", () => {
    render(<QueryComposer onSubmit={noop} />);
    const counter = screen.getByText(queryCounter(0));
    expect(counter).toBeVisible();
    expect(counter).toHaveAttribute("data-counter", "within");
  });

  it("counts what is typed", async () => {
    render(<QueryComposer onSubmit={noop} />);
    await user().type(field(), "abc");
    expect(screen.getByText(queryCounter(3))).toBeInTheDocument();
  });

  it("warns near the bound and turns critical over it", () => {
    const { rerender } = render(
      <QueryComposer onSubmit={noop} value={"x".repeat(7_200)} />,
    );
    expect(screen.getByText(queryCounter(7_200))).toHaveAttribute(
      "data-counter",
      "near",
    );

    rerender(<QueryComposer onSubmit={noop} value={"x".repeat(MAX_QUERY_LEN)} />);
    expect(screen.getByText(queryCounter(MAX_QUERY_LEN))).toHaveAttribute(
      "data-counter",
      "near",
    );

    rerender(
      <QueryComposer onSubmit={noop} value={"x".repeat(MAX_QUERY_LEN + 1)} />,
    );
    expect(screen.getByText(queryCounter(MAX_QUERY_LEN + 1))).toHaveAttribute(
      "data-counter",
      "over",
    );
  });

  it("blocks submit client-side over the bound, and says by how much", async () => {
    const onSubmit = vi.fn();
    render(
      <QueryComposer onSubmit={onSubmit} value={"x".repeat(MAX_QUERY_LEN + 1)} />,
    );

    // The refusal is attached to the field, not merely printed near it.
    expect(field()).toHaveAttribute("aria-invalid", "true");
    const describedBy = (field().getAttribute("aria-describedby") ?? "").split(" ");
    const stated = describedBy
      .map((id) => document.getElementById(id))
      .filter((node): node is HTMLElement => node !== null);
    expect(
      stated.some((node) =>
        (node.textContent ?? "").includes(queryOverLimit(MAX_QUERY_LEN + 1)),
      ),
    ).toBe(true);
    expect(submitButton()).toHaveAttribute("aria-disabled", "true");

    await user().click(submitButton());
    fireEvent.keyDown(field(), { key: "Enter", metaKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("refuses rather than truncating — no maxLength, and the text survives", () => {
    const long = "x".repeat(MAX_QUERY_LEN + 500);
    render(<QueryComposer onSubmit={noop} value={long} />);
    expect(field()).not.toHaveAttribute("maxLength");
    expect(field().value).toHaveLength(long.length);
  });

  it("pastes over the bound in full", async () => {
    render(<QueryComposer onSubmit={noop} />);
    const long = "y".repeat(MAX_QUERY_LEN + 12);
    const typist = user();
    await typist.click(field());
    await typist.paste(long);
    expect(field().value).toHaveLength(long.length);
    expect(screen.getByText(queryCounter(long.length))).toHaveAttribute(
      "data-counter",
      "over",
    );
  });
});

// ---------------------------------------------------------------------------
// Criterion 3 — the h1 is the first thing on screen.
// ---------------------------------------------------------------------------

describe("criterion 3 — the h1 leads", () => {
  it("is the document's only h1 and its first heading", () => {
    render(<QueryComposer onSubmit={noop} />);
    const headings = screen.getAllByRole("heading");
    expect(headings).toHaveLength(1);
    expect(headings[0]).toBe(screen.getByRole("heading", { level: 1 }));
  });

  it("precedes every other part of the composer in document order", () => {
    render(<QueryComposer onSubmit={noop} />);
    const heading = screen.getByRole("heading", { level: 1 });
    const after = [
      field(),
      screen.getByText(queryCounter(0)),
      screen.getByText(LANDING.disclosure),
      submitButton(),
      screen.getByRole("list", { name: COMPOSER.processLabel }),
    ];
    for (const node of after) {
      expect(
        heading.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });

  it("has only the eyebrow above it", () => {
    render(<QueryComposer onSubmit={noop} />);
    const header = screen.getByRole("heading", { level: 1 })
      .parentElement as HTMLElement;
    expect(header.children).toHaveLength(2);
    expect(header.children[0]).toHaveTextContent(LANDING.eyebrow);
    // The header is the form's first child, so nothing of the composer's
    // own renders above the prompt.
    const form = header.parentElement as HTMLElement;
    expect(form.tagName).toBe("FORM");
    expect(form.firstElementChild).toBe(header);
  });
});

// ---------------------------------------------------------------------------
// Criterion 4 — Cmd/Ctrl+Enter.
// ---------------------------------------------------------------------------

describe("criterion 4 — the keyboard shortcut, finally tested", () => {
  it.each([
    ["meta", { metaKey: true }],
    ["ctrl", { ctrlKey: true }],
  ])("%s+Enter submits the trimmed question", (_name, modifier) => {
    const onSubmit = vi.fn();
    render(<QueryComposer onSubmit={onSubmit} value={`  ${QUESTION}  `} />);
    fireEvent.keyDown(field(), { key: "Enter", ...modifier });
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith(QUESTION);
  });

  it("a bare Enter does not submit — a question is often more than a line", () => {
    const onSubmit = vi.fn();
    render(<QueryComposer onSubmit={onSubmit} value={QUESTION} />);
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does nothing while a submission is in flight", () => {
    const onSubmit = vi.fn();
    render(<QueryComposer onSubmit={onSubmit} value={QUESTION} pending />);
    fireEvent.keyDown(field(), { key: "Enter", metaKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does nothing when the field is blank", () => {
    const onSubmit = vi.fn();
    render(<QueryComposer onSubmit={onSubmit} value="   " />);
    fireEvent.keyDown(field(), { key: "Enter", metaKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Criterion 5 — one submission per intent.
// ---------------------------------------------------------------------------

describe("criterion 5 — exactly one submission per intent", () => {
  /** An `onSubmit` that never settles, i.e. a real request in flight. */
  function pendingSubmit() {
    return vi.fn((_query: string) => new Promise<void>(() => undefined));
  }

  it("survives a double click", async () => {
    const onSubmit = pendingSubmit();
    render(<QueryComposer onSubmit={onSubmit} value={QUESTION} />);
    await user().dblClick(submitButton());
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("survives two clicks dispatched in the same tick", () => {
    const onSubmit = pendingSubmit();
    render(<QueryComposer onSubmit={onSubmit} value={QUESTION} />);
    const button = submitButton();
    fireEvent.click(button);
    fireEvent.click(button);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("survives Enter-then-click and click-then-Enter", () => {
    const onSubmit = pendingSubmit();
    render(<QueryComposer onSubmit={onSubmit} value={QUESTION} />);
    fireEvent.keyDown(field(), { key: "Enter", metaKey: true });
    fireEvent.click(submitButton());
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("survives React StrictMode's double-invoked mount", async () => {
    const onSubmit = pendingSubmit();
    render(
      <StrictMode>
        <QueryComposer onSubmit={onSubmit} value={QUESTION} />
      </StrictMode>,
    );
    // Mounting alone submits nothing: there is no effect on this path.
    expect(onSubmit).not.toHaveBeenCalled();
    await user().click(submitButton());
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("refuses while the caller says a submission is pending", async () => {
    const onSubmit = vi.fn();
    render(<QueryComposer onSubmit={onSubmit} value={QUESTION} pending />);
    await user().click(submitButton());
    expect(onSubmit).not.toHaveBeenCalled();
    expect(submitButton()).toHaveTextContent(LANDING.submitPending);
    expect(submitButton()).toHaveAttribute("aria-busy", "true");
  });

  it("accepts the next intent once the first one has settled", async () => {
    let settle = (): void => undefined;
    const onSubmit = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          settle = resolve;
        }),
    );
    render(<QueryComposer onSubmit={onSubmit} value={QUESTION} />);
    await user().click(submitButton());
    expect(onSubmit).toHaveBeenCalledTimes(1);

    settle();
    await Promise.resolve();
    await user().click(submitButton());
    expect(onSubmit).toHaveBeenCalledTimes(2);
  });
});

// ---------------------------------------------------------------------------
// Criterion 6 — failure keeps the question, and nothing retries.
// ---------------------------------------------------------------------------

describe("criterion 6 — the question is kept and only a manual resubmit exists", () => {
  it("keeps the typed question and announces the normalized cause", () => {
    render(
      <QueryComposer onSubmit={noop} value={QUESTION} failure={RATE_LIMITED} />,
    );
    expect(field().value).toBe(QUESTION);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(FAILURE_COPY.rate_limited.sentence);
    expect(alert).toHaveTextContent(COMPOSER.retained);
    expect(alert).toHaveTextContent(COMPOSER.noAutoRetry);
  });

  it("offers one submit control, not a second 'retry' button", () => {
    render(
      <QueryComposer onSubmit={noop} value={QUESTION} failure={RATE_LIMITED} />,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toBe(submitButton());
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
  });

  it("that control resubmits only when it is pressed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const onSubmit = vi.fn();
      render(
        <QueryComposer
          onSubmit={onSubmit}
          value={QUESTION}
          failure={RATE_LIMITED}
        />,
      );

      // R-01: no timer, no effect and no connectivity event may resubmit.
      await vi.advanceTimersByTimeAsync(120_000);
      window.dispatchEvent(new Event("online"));
      await vi.advanceTimersByTimeAsync(120_000);
      expect(onSubmit).not.toHaveBeenCalled();

      fireEvent.click(submitButton());
      expect(onSubmit).toHaveBeenCalledExactlyOnceWith(QUESTION);
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders an info-severity failure without interrupting", () => {
    // 03 §7.3: `role="alert"` is for what is worth interrupting for. A
    // cancelled request is not, so it is ordinary content — and the
    // banner still renders, which is what stops it from vanishing.
    const cancelled: ApiFailure = { kind: "cancelled", message: "", raw: null };
    render(
      <QueryComposer onSubmit={noop} value={QUESTION} failure={cancelled} />,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(FAILURE_COPY.cancelled.sentence)).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Criterion 7 — unreachable refuses with the reason attached.
// ---------------------------------------------------------------------------

describe("criterion 7 — aria-disabled with the reason, never a bare disabled", () => {
  it("attaches 03 §2.2 row 4's sentence to the control", () => {
    render(
      <QueryComposer onSubmit={noop} value={QUESTION} unreachable={UNREACHABLE} />,
    );
    const button = submitButton();

    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    // Not busy: nothing is in flight, and saying so would announce work
    // that is not happening.
    expect(button).not.toHaveAttribute("aria-busy");

    const ids = (button.getAttribute("aria-describedby") ?? "").split(" ");
    const reason = ids
      .map((id) => document.getElementById(id))
      .find((node) => node?.textContent === FAILURE_COPY.upstream_unavailable.sentence);
    expect(reason).toBeTruthy();
    expect(reason).toBeVisible();
  });

  it("stays focusable, so a keyboard user is not stranded", async () => {
    const onSubmit = vi.fn();
    render(
      <QueryComposer
        onSubmit={onSubmit}
        value={QUESTION}
        unreachable={UNREACHABLE}
      />,
    );
    submitButton().focus();
    expect(submitButton()).toHaveFocus();
    // Focus survives, and pressing it still refuses. `disabled` would have
    // taken both the focus and the explanation away.
    await user().keyboard("{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(submitButton()).toHaveFocus();
  });

  it("refuses the click and the shortcut", async () => {
    const onSubmit = vi.fn();
    render(
      <QueryComposer
        onSubmit={onSubmit}
        value={QUESTION}
        unreachable={UNREACHABLE}
      />,
    );
    await user().click(submitButton());
    fireEvent.keyDown(field(), { key: "Enter", metaKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps the blank-field reason described but off the screen", () => {
    render(<QueryComposer onSubmit={noop} />);
    const button = submitButton();
    expect(button).toHaveAttribute("aria-disabled", "true");
    const ids = (button.getAttribute("aria-describedby") ?? "").split(" ");
    const reason = ids
      .map((id) => document.getElementById(id))
      .find((node) => node?.textContent === COMPOSER.emptyQuestion);
    expect(reason).toBeTruthy();
    // Scolding a pristine page for not having been typed in yet is noise;
    // the reason belongs in the description, not on the screen.
    expect(reason).toHaveClass(VISUALLY_HIDDEN_CLASS);
  });
});

// ---------------------------------------------------------------------------
// Criterion 8 — H7, the orphan thread.
// ---------------------------------------------------------------------------

describe("criterion 8 — a failure after the thread was created offers it", () => {
  it("says so and links to the empty thread", () => {
    render(
      <QueryComposer
        onSubmit={noop}
        value={QUESTION}
        failure={RATE_LIMITED}
        orphanThreadHref="/c/conv-1"
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(COMPOSER.orphanSentence);
    expect(
      within(alert).getByRole("link", { name: COMPOSER.orphanAction }),
    ).toHaveAttribute("href", "/c/conv-1");
  });

  it("offers nothing when no thread was created", () => {
    render(
      <QueryComposer onSubmit={noop} value={QUESTION} failure={RATE_LIMITED} />,
    );
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText(COMPOSER.orphanSentence)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Criterion 9 — the ten stories exist.
// ---------------------------------------------------------------------------

describe("criterion 9 — the named story set", () => {
  it("exports every state the work order names", () => {
    for (const name of [
      "Empty",
      "Filled",
      "NearLimit",
      "OverLimit",
      "Submitting",
      "RateLimited",
      "Unauthorized",
      "UpstreamDown",
      "ProxyMisconfigured",
      "FollowUp",
    ]) {
      expect(stories, name).toHaveProperty(name);
    }
  });

  it("none of them can submit — the one billable call is unreachable", () => {
    // The shared arg is a handler that does nothing, so no story can reach
    // `POST /research` even by being interacted with in the addon's runner.
    expect(typeof stories.default.args.onSubmit).toBe("function");
    expect(stories.default.args.onSubmit.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Criterion 10 — H12.
// ---------------------------------------------------------------------------

describe(`criterion 10 — no code path passes ${BYPASS_FIELD}`, () => {
  it("the surfaces this work order adds never name the field", () => {
    // The repo-wide guarantee is `web/tests/api.test.ts`'s containment
    // scan, which walks app/, components/, lib/ and tests/ and allows the
    // literal only under lib/api. This narrower check exists so a failure
    // here names WO-13's own files, and it spells the field the same way
    // that test does — from parts — so the file it lives in does not
    // become the violation it is looking for.
    const files = [
      "components/features/QueryComposer.tsx",
      "components/features/LandingComposer.tsx",
      "components/features/QueryComposer.stories.tsx",
    ];
    for (const file of files) {
      const source = readFileSync(path.join(REPO_ROOT, "web", file), "utf8");
      expect(source, file).not.toContain(BYPASS_FIELD);
    }
  });

  it("offers no control that would set it", () => {
    render(<QueryComposer onSubmit={noop} value={QUESTION} />);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
    // 03 §8.4 and D-010 ruling 5: nothing on the surface may even offer
    // the idea, which is the half a component could reintroduce without
    // touching a request.
    expect(document.body.textContent ?? "").not.toMatch(
      /bypass|skip (?:the )?(?:review|plan)/i,
    );
  });
});

// ---------------------------------------------------------------------------
// The follow-up variant (03 §4.3).
// ---------------------------------------------------------------------------

describe("the follow-up variant", () => {
  it("is compact: its own field, no display prompt, no process strip", () => {
    render(<QueryComposer variant="follow-up" onSubmit={noop} />);
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.getByLabelText(COMPOSER.followUpLabel)).toHaveAttribute(
      "placeholder",
      COMPOSER.followUpPlaceholder,
    );
  });

  it("still carries the billability disclosure above its button", () => {
    // A follow-up starts a billable run too, so the sentence that says so
    // is not landing decoration.
    render(<QueryComposer variant="follow-up" onSubmit={noop} />);
    const disclosure = screen.getByText(LANDING.disclosure);
    expect(disclosure.nextElementSibling).toBe(submitButton());
  });
});

// ---------------------------------------------------------------------------
// The uncontrolled field, which the follow-up variant will use.
// ---------------------------------------------------------------------------

describe("value handling", () => {
  it("mirrors an uncontrolled value and reports every change", async () => {
    const onValueChange = vi.fn();
    const onSubmit = vi.fn();
    render(
      <QueryComposer
        onSubmit={onSubmit}
        defaultValue="ab"
        onValueChange={onValueChange}
      />,
    );
    await user().type(field(), "c");
    expect(field().value).toBe("abc");
    expect(onValueChange).toHaveBeenLastCalledWith("abc");

    fireEvent.keyDown(field(), { key: "Enter", metaKey: true });
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith("abc");
  });

  it("lets a controlled caller keep the value on a failure", () => {
    const { rerender } = render(
      <QueryComposer onSubmit={noop} value={QUESTION} />,
    );
    rerender(
      <QueryComposer onSubmit={noop} value={QUESTION} failure={RATE_LIMITED} />,
    );
    expect(field().value).toBe(QUESTION);
  });
});
