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
  useReportPipeline,
  useReportRenderer,
} from "@/lib/queries/conversations";
import { loadedReportRenderer } from "@/lib/report/renderer";

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

  /**
   * WO-S2d — the same guarantee, through the richer hook.
   *
   * `useReportPipeline` is what `ThreadTimeline` holds its loading frame on,
   * so it is now the hook that could break "a collapsed turn never parses" —
   * and it must break it in neither direction: with `needed` false it may not
   * start the import, and it may not claim to have SETTLED either, because a
   * caller reading `settled` as "nothing to wait for" would release a frame
   * on a pipeline that was never asked for.
   */
  it("starts nothing, and settles nothing, while nothing needs it", async () => {
    const { result } = renderHook(() => useReportPipeline(false));
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.renderer).toBeNull();
    expect(result.current.settled).toBe(false);
    expect(markdown.imports).toBe(0);
    expect(markdown.parses).toBe(0);
    expect(loadedReportRenderer()).toBeNull();
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

/* =========================================================================
 * WO-S2d — the pipeline's two facts, and the one that is a layout promise.
 *
 * These run after the block above on purpose: the module-level cache is
 * loaded by now, which is the state the assertions below are about.
 * ====================================================================== */

describe("WO-S2d — an already-loaded pipeline is not a loading one", () => {
  /**
   * THE ASSERTION THE WHOLE HOLD RESTS ON, AND WHY IT HAS NO `waitFor`.
   *
   * `ThreadTimeline` holds its loading frame until the pipeline has settled
   * so that the briefing can mount at the height it keeps. If the surface
   * that mounts a beat later had to go round the resolved promise again, it
   * would render `ReportReader`'s 216px skeleton for one more commit — and a
   * commit is a paint, which is the whole currency here. So the renderer must
   * be there on the FIRST render, synchronously, with nothing awaited between
   * this hook mounting and reading it.
   */
  it("hands a mounting surface the renderer in its first render, not a tick later", async () => {
    await loadReportRenderer();

    const { result } = renderHook(() => useReportPipeline(true));

    expect(result.current.settled).toBe(true);
    expect(result.current.renderer).not.toBeNull();
    expect(result.current.renderer).toBe(loadedReportRenderer());
  });

  it("reads the cache and never fills it, so `needed: false` still imports nothing", () => {
    const before = markdown.imports;
    const { result } = renderHook(() => useReportPipeline(false));

    expect(result.current.renderer).toBeNull();
    expect(result.current.settled).toBe(false);
    expect(markdown.imports).toBe(before);
  });

  it("agrees with `useReportRenderer`, which is now a view of it", async () => {
    const pipeline = renderHook(() => useReportPipeline(true));
    const renderer = renderHook(() => useReportRenderer(true));

    await waitFor(() => expect(renderer.result.current).not.toBeNull());
    expect(pipeline.result.current.renderer).toBe(renderer.result.current);
  });
});
