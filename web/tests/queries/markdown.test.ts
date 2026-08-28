// WO-11 criterion 7 — conversation detail parses Markdown lazily on
// expand, and a collapsed turn does not parse.
//
// The parse boundary is a dynamic `import("react-markdown")`, so the
// observable fact is whether that module is loaded at all. This file
// mocks it with a factory that counts two separate things: how many
// times the module is EVALUATED (the import happened) and how many times
// the renderer is INVOKED (the parse happened). A collapsed turn must
// leave both at zero.
//
// It lives in its own file because the mock and the module-level
// renderer cache are per-file in Vitest, and because the first
// assertion — "zero" — is only meaningful before anything has expanded.
// The tests below therefore run in source order, collapsed first.

import { createElement, type ReactElement, type ReactNode } from "react";

import { describe, expect, it, vi } from "vitest";

import type { ConversationDetail } from "@/lib/api/index";
import {
  conversationTurns,
  loadReportRenderer,
  useReportRenderer,
} from "@/lib/queries/conversations";

import { loadFixture } from "../support/msw";
import { act, render, renderHook, screen, waitFor } from "../support/render";

const markdown = vi.hoisted(() => ({ imports: 0, parses: 0 }));

vi.mock("react-markdown", () => {
  // Runs the first time — and only the first time — the module is
  // imported. If a collapsed turn ever triggers the import, this counter
  // is how we find out.
  markdown.imports += 1;
  return {
    default: ({ children }: { children: ReactNode }): ReactElement => {
      markdown.parses += 1;
      return createElement("article", { "data-testid": "report" }, children);
    },
  };
});

const DETAIL = loadFixture("conversations.detail").body as ConversationDetail;

describe("a collapsed turn does not parse (criterion 7)", () => {
  it("holds the report as a raw string and loads no Markdown pipeline", async () => {
    // The whole detail response, turned into turns — the state the
    // thread renders in before anyone expands anything.
    const turns = conversationTurns(DETAIL);
    expect(turns).toHaveLength(1);
    expect(typeof turns[0]?.report).toBe("string");

    const { result } = renderHook(() => useReportRenderer(false));
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current).toBeNull();
    expect(markdown.imports).toBe(0);
    expect(markdown.parses).toBe(0);
  });
});

describe("expanding is what parses", () => {
  it("loads the pipeline on expand and renders the report through it", async () => {
    const { result, rerender } = renderHook(
      ({ expanded }: { expanded: boolean }) => useReportRenderer(expanded),
      { initialProps: { expanded: false } }
    );
    expect(markdown.imports).toBe(0);

    rerender({ expanded: true });
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(markdown.imports).toBe(1);
    // Loading is not yet parsing: nothing has rendered the report.
    expect(markdown.parses).toBe(0);

    const Renderer = result.current;
    if (Renderer === null) throw new Error("renderer never loaded");
    render(createElement(Renderer, null, DETAIL.jobs[0]?.report ?? ""));

    expect(markdown.parses).toBe(1);
    expect(screen.getByTestId("report")).toHaveTextContent(
      "Retrieval-Augmented Verification"
    );
  });

  it("loads the pipeline once, however many turns expand", async () => {
    const first = renderHook(() => useReportRenderer(true));
    await waitFor(() => expect(first.result.current).not.toBeNull());
    const second = renderHook(() => useReportRenderer(true));
    await waitFor(() => expect(second.result.current).not.toBeNull());

    await loadReportRenderer();
    expect(markdown.imports).toBe(1);
    expect(first.result.current).toBe(second.result.current);
  });

  it("goes back to null when a turn collapses again", async () => {
    const { result, rerender } = renderHook(
      ({ expanded }: { expanded: boolean }) => useReportRenderer(expanded),
      { initialProps: { expanded: true } }
    );
    await waitFor(() => expect(result.current).not.toBeNull());

    rerender({ expanded: false });
    expect(result.current).toBeNull();
  });
});
