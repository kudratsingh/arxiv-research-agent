"use client";

/**
 * ThreadRailBridge — the only part of the shell that touches the data layer.
 *
 * It exists so that `WorkbenchShell` does not. 04-ARCHITECTURE.md §5.1's
 * layer rule is that a component's states are reachable by passing props,
 * "so their stories need no MSW and no network"; the shell's `rail` prop is
 * that seam, and this module is what the `(workspace)` layout passes
 * through it. Keeping the import here rather than as the shell's default
 * has one measurable consequence beyond tidiness: the Storybook project
 * never loads `lib/api` at all, so the coverage report counts the client
 * once instead of once per Vitest project.
 *
 * WHAT IT PRESERVES. `ConversationsShell.tsx:17-19` navigated with
 * `router.push('/c/' + id)`, or `/` for the empty id, and passed the route's
 * own `params.id` as the active thread. Both survive verbatim — the active
 * id now comes from `usePathname()` because a layout has no `params`, and it
 * is decoded because a pathname is percent-encoded and `params.id` was not.
 *
 * WO-14's `ThreadRail` replaces `ConversationSidebar` and this bridge with
 * it; the shell's `rail` prop is the only thing that has to survive.
 */

import { usePathname, useRouter } from "next/navigation";

import ConversationSidebar from "@/components/ConversationSidebar";

/** `/c/<id>` → `<id>`, decoded. Anything else → `null`. */
export function activeConversationIdFrom(pathname: string | null): string | null {
  const match = /^\/c\/([^/]+)/.exec(pathname ?? "");
  if (!match?.[1]) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    // A malformed escape sequence in the URL is not a reason to blank the
    // rail; the raw segment still identifies the row to highlight.
    return match[1];
  }
}

export default function ThreadRailBridge() {
  const router = useRouter();
  const pathname = usePathname();

  return (
    <ConversationSidebar
      activeConversationId={activeConversationIdFrom(pathname)}
      onNavigate={(conversationId) => {
        router.push(conversationId ? `/c/${conversationId}` : "/");
      }}
    />
  );
}
