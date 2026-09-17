/**
 * WO-S2d — the Markdown chunk that will not load.
 *
 * WHY THIS IS A FILE OF ITS OWN. `loadReportRenderer` caches its promise at
 * module scope, and Vitest gives each test FILE its own module registry — so
 * "the import rejected" is a state that can only be established once, and only
 * where nothing has already loaded the pipeline successfully. The mock factory
 * below throws, which is what a dynamic `import()` of a chunk that 404s does.
 *
 * WHAT IT GUARDS. `ThreadTimeline` now holds its loading frame until the
 * pipeline has SETTLED, which is the only reason `settled` exists separately
 * from `renderer`: a hold keyed on `renderer !== null` would never release
 * against a stale deployment, and the thread — transcript, composer and all —
 * would be a skeleton for ever. A failed pipeline must leave the reader's own
 * loading state on screen and nothing more, which is what it did before the
 * hold existed.
 */

import { describe, expect, it, vi } from "vitest";

import { useReportPipeline, useReportRenderer } from "@/lib/queries/conversations";
import { loadReportRenderer, loadedReportRenderer } from "@/lib/report/renderer";

import { renderHook, waitFor } from "../support/render";

vi.mock("react-markdown", () => {
  throw new Error("chunk 404");
});

describe("a pipeline that cannot load settles anyway", () => {
  it("rejects rather than hanging, and caches nothing", async () => {
    await expect(loadReportRenderer()).rejects.toThrow();
    expect(loadedReportRenderer()).toBeNull();
  });

  it("reports settled with no renderer, so a caller waiting on it is released", async () => {
    const { result } = renderHook(() => useReportPipeline(true));

    expect(result.current.settled).toBe(false);
    await waitFor(() => expect(result.current.settled).toBe(true));
    expect(
      result.current.renderer,
      "a failed import must not hand back a renderer; the surfaces below it " +
        "render their own loading state instead.",
    ).toBeNull();
  });

  it("leaves `useReportRenderer` null, which is the reader's loading state", async () => {
    const { result } = renderHook(() => useReportRenderer(true));

    await waitFor(() => expect(loadedReportRenderer()).toBeNull());
    expect(result.current).toBeNull();
  });
});
