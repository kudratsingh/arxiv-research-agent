// THE Markdown boundary — one renderer, loaded once, lazily (WO-18 c2, c3).
//
// WO-11 put this at the foot of `lib/queries/conversations.ts`, because the
// only thing that needed it was a conversation turn expanding. WO-18 moved
// the three declarations here and left `conversations.ts` re-exporting them,
// for one concrete reason rather than for tidiness:
//
//   `conversations.ts` imports `@tanstack/react-query` and `lib/api`. A
//   Storybook story for the reading surface, or any future consumer that
//   only wants to render Markdown, would drag the whole query layer into
//   its module graph to reach a dynamic `import()` that has nothing to do
//   with it. Splitting the boundary out costs one file and keeps
//   `useReportRenderer` — which IS a query-layer hook — exactly where WO-11
//   put it.
//
// NOTHING ELSE IN THE PRODUCT MAY IMPORT `react-markdown`.
// `web/tests/patterns/ReportReader.test.tsx` scans the tree and asserts
// that, with the two legacy components WO-20 stops composing and WO-31
// deletes as the only named exceptions. That is what makes the divergence
// 04 §5.1 records — `ReportView.tsx:39-48` against
// `ConversationThread.tsx:301-306` — unrepeatable on the new surface: there
// is one pipeline, so a current turn and a historical turn cannot be
// configured differently.

import { createElement, type ComponentType } from "react";

// Type-only, so naming the prop shape pulls nothing into a route's
// first-load JS.
import type { Components as MarkdownComponents } from "react-markdown";

/** The props every briefing is rendered through. */
export interface ReportRendererProps {
  /** The raw Markdown body. */
  children: string;
  /**
   * Element overrides — WO-18's labelled `ScrollRegion` around a wide table
   * or a fenced block. Optional, so a caller that wants plain output passes
   * nothing.
   */
  components?: MarkdownComponents;
}

/** The one renderer's shape. */
export type ReportRenderer = ComponentType<ReportRendererProps>;

let rendererPromise: Promise<ReportRenderer> | null = null;

/**
 * Load the Markdown pipeline — and only then.
 *
 * A conversation detail response carries every report body in full
 * (`schemas.py:184-191`), so a thread with ten turns holds ten Markdown
 * documents in memory the moment it loads. Parsing them all to render a
 * collapsed list is work nobody asked for, and `react-markdown` +
 * `remark-gfm` are a meaningful chunk on a route whose budget is already
 * tight (RC-01). The dynamic import keeps both out of the route's
 * first-load JS until a turn is actually expanded, and the module-level
 * promise means the second expansion pays nothing.
 *
 * WO-18 FOLDED `remark-gfm` INTO THE BOUNDARY rather than letting a surface
 * pass it as a plugin prop. Two reasons, neither of them tidiness:
 *
 *   1. MUST-KEEP 7 is "Markdown/GFM **without raw HTML passthrough**", and
 *      that is a property of the pipeline, not of a call site. Composed
 *      here, every caller gets tables, strikethrough and task lists, and no
 *      caller can add `rehype-raw` without editing this function.
 *   2. `remarkPlugins={[remarkGfm]}` at a surface would be a STATIC import
 *      of `remark-gfm` in that surface's module — the plugin in the route's
 *      first-load JS while the renderer it belongs to is still lazy.
 *
 * There is no `rehype-raw` in this chain and nothing sets `skipHtml: false`,
 * so `react-markdown`'s default holds: raw HTML in a briefing is text. A
 * report body is LLM output that reached us through a database; treating it
 * as markup would be the one place in this product where a stored string
 * becomes executable.
 */
export function loadReportRenderer(): Promise<ReportRenderer> {
  rendererPromise ??= Promise.all([
    import("react-markdown"),
    import("remark-gfm"),
  ]).then(([markdown, gfm]) => {
    const ReactMarkdown = markdown.default as unknown as ComponentType<
      Record<string, unknown>
    >;
    const plugins = [gfm.default];
    const Renderer: ReportRenderer = ({ children, components }) =>
      createElement(ReactMarkdown, { remarkPlugins: plugins, components }, children);
    Renderer.displayName = "ReportRenderer";
    return Renderer;
  });
  return rendererPromise;
}
