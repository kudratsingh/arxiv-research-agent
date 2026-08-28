"use client";

/**
 * ThreadList — every state of the thread rail, reachable by passing props
 * (RC-10's rename of `ConversationList`; WO-14).
 *
 * WHAT LIVES HERE AND WHAT LIVES IN features/ThreadRail.tsx. 04 §5.1's
 * layer rule: a pattern "takes plain props and never calls a hook that
 * fetches", which is what lets all eight of 03 §4.2's rail states be
 * photographed as stories with no MSW and no network. So this module owns
 * the markup, the row's `?job=` rule and the confirmation dialog's
 * placement; the feature owns the queries, the mutation and the state
 * machine that drives them.
 *
 * THE TWO BEHAVIOURAL FIXES 03 §4.2 NAMES ARE BOTH IN THIS FILE.
 *
 *   1. `?job=` PRESERVATION (criterion 1, R-02, MUST-KEEP 1). The row for
 *      the thread whose run is currently attached keeps the query
 *      parameter, so navigating to the thread you are already running does
 *      not detach a paid run. `threadRowHref` is the rule, exported so it
 *      can be tested as a function rather than only through a click.
 *
 *   2. A PERMANENTLY FOCUSABLE DESTRUCTIVE CONTROL (criterion 2). The
 *      baseline's delete is `opacity-0 group-hover:opacity-100`
 *      (`ConversationSidebar.tsx:133`) — invisible to a keyboard user, to a
 *      touch user, and to anyone who cannot hover. Here it is a real
 *      `<button>` inside a real menu (RC-09: the row overflow is the one
 *      genuine menu left in the product), rendered at full opacity in every
 *      state, in the tab order, at all times. There is no `opacity-0` and
 *      no `group-hover` anywhere in this file, and
 *      `web/tests/threads/list.test.tsx` asserts that against the source
 *      text as well as against the behaviour.
 *
 * IT CARRIES NO STRINGS OF ITS OWN. Every word arrives from
 * `web/lib/copy/threads.ts`; `copy/no-inline-text` makes that structural.
 * The one composed string is the row menu's accessible name, which joins a
 * dictionary word to the user's own thread title —
 * `web/tests/copy/threads-rail-copy.test.ts` runs `threadMenuLabel` through
 * the same deny-list the dictionary faces, so the composition is gated too.
 */

import Link from "next/link";
import { useEffect, useRef, type ReactNode } from "react";

import { Button } from "@/components/primitives/Button";
import { Menu, MenuItem, MenuSeparator } from "@/components/primitives/Menu";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { cx } from "@/components/primitives/styles";
import { THREAD_RAIL, THREAD_ROW, deleteDialog } from "@/lib/copy/threads";

import { ConfirmDialog } from "./ConfirmDialog";
import { EmptyState } from "./EmptyState";
import { StatusBanner } from "./StatusBanner";
import {
  THREAD_RAIL_HEADING_ID,
  ThreadListSkeleton,
  ThreadRailFrame,
} from "./ThreadRailFrame";
import "./threads.css";

/**
 * One row's data.
 *
 * Deliberately NOT `ConversationListItem`. RC-12 register 3 keeps the API's
 * noun on the wire and register 2 puts the product's noun in the component,
 * and this interface is where the two meet: the feature maps
 * `conversation_id` onto `id` once, and every state below is expressible
 * without the pattern knowing what an HTTP response looks like.
 */
export interface ThreadSummary {
  id: string;
  title: string;
}

/** The inline notice at the top of the rail (03 §2.2 row 4). */
export interface ThreadRailNotice {
  sentence: string;
  recovery?: string;
  /**
   * Present ONLY for a failed read. A failed DELETE gets a notice with no
   * action at all: 04 §9.1 H6 and R-01 forbid replaying a write, and the
   * `onRetry` this calls is wired to `refetch()` — `GET /conversations` and
   * nothing else (criterion 6).
   */
  onRetry?: () => void;
  retryLabel?: string;
}

export interface ThreadListProps {
  threads: readonly ThreadSummary[];
  /** The first page has not arrived. Renders skeleton rows, never a spinner. */
  loading?: boolean;
  /** The thread the route is on, from `usePathname()`. */
  activeConversationId?: string | null;
  /**
   * The run attached to the current route, from `?job=`.
   *
   * The rail claims nothing about the run's server-side status — that is
   * the trace spine's job (WO-15) and the spine is the product's single
   * `role="status"`. What this value states is narrower and certain: THIS
   * browser has a run attached to that thread, so that row must not drop
   * it.
   */
  attachedJobId?: string | null;
  canLoadMore?: boolean;
  isLoadingMore?: boolean;
  onLoadMore?: () => void;
  notice?: ThreadRailNotice | null;
  /** Called with a full href, so the caller pushes exactly what the row points at. */
  onNavigate?: (href: string) => void;
  /** The overflow menu's destructive item. Opens the confirmation. */
  onDeleteRequest?: (thread: ThreadSummary) => void;
  /** The thread the confirmation is open for, or `null` when it is closed. */
  pendingDelete?: ThreadSummary | null;
  onDeleteCancel?: () => void;
  onDeleteConfirm?: () => void;
  /** The DELETE is in flight: the confirm button is busy, Cancel still works. */
  deletePending?: boolean;
  /** Extra classes for the rail's root, e.g. inside the drawer. */
  className?: string;
  /** Overridden by stories that render two rails on one page. */
  headingId?: string;
}

/**
 * The `?job=` preservation rule (criterion 1), as a pure function.
 *
 * 03 §2.1: "a thread row in the rail that points at the thread you are
 * currently running loses `?job=`. Today that silently detaches a paid run.
 * The new rail keeps the active run's `?job=` on its own row". It applies
 * to exactly one row — the attached thread's own — because that is the only
 * row where the parameter means anything: `?job=` names a run inside a
 * specific thread, and carrying it onto a different thread's row would
 * point at a run that thread never had.
 */
export function threadRowHref(
  conversationId: string,
  activeConversationId: string | null | undefined,
  attachedJobId: string | null | undefined,
): string {
  const base = `/c/${encodeURIComponent(conversationId)}`;
  if (!attachedJobId || conversationId !== activeConversationId) return base;
  return `${base}?job=${encodeURIComponent(attachedJobId)}`;
}

/**
 * The row menu's accessible name.
 *
 * "Thread actions" alone would give every row in the list the same name,
 * which is a control a screen-reader user cannot tell from its neighbour.
 * The title is the user's own words and passes through unedited (the same
 * rule `deleteDialog()` follows); only the word before it comes from the
 * dictionary.
 */
export function threadMenuLabel(title: string): string {
  const named = title.trim();
  return named === "" ? THREAD_ROW.menuLabel : `${THREAD_ROW.menuLabel}: ${named}`;
}

function OverflowGlyph() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="16" height="16">
      <circle cx="8" cy="3" r="1.4" fill="currentColor" />
      <circle cx="8" cy="8" r="1.4" fill="currentColor" />
      <circle cx="8" cy="13" r="1.4" fill="currentColor" />
    </svg>
  );
}

function railState(
  loading: boolean,
  notice: ThreadRailNotice | null | undefined,
  count: number,
): "loading" | "empty" | "list" | "error" {
  if (loading) return "loading";
  if (notice?.onRetry !== undefined && count === 0) return "error";
  if (count === 0) return "empty";
  return "list";
}

export function ThreadList({
  threads,
  loading = false,
  activeConversationId = null,
  attachedJobId = null,
  canLoadMore = false,
  isLoadingMore = false,
  onLoadMore,
  notice = null,
  onNavigate,
  onDeleteRequest,
  pendingDelete = null,
  onDeleteCancel,
  onDeleteConfirm,
  deletePending = false,
  className,
  headingId = THREAD_RAIL_HEADING_ID,
}: ThreadListProps) {
  const state = railState(loading, notice, threads.length);
  const dialogCopy = deleteDialog(pendingDelete?.title ?? "");
  const rootRef = useRef<HTMLDivElement>(null);

  /**
   * Focus restoration for the confirmation (criterion 3), which Radix
   * cannot do here and WO-08 already hit the same wall for.
   * `DialogContentModal.onCloseAutoFocus` calls `preventDefault()` and then
   * focuses `Dialog.Trigger`'s ref — so a dialog opened by anything that is
   * not a `Dialog.Trigger` restores focus to nothing at all, and this one
   * is opened by a MENU ITEM in a portal, three components away.
   *
   * So the rail restores it, in a PASSIVE effect for the reason
   * `WorkbenchShell.tsx` records: Radix's own focus handling runs in a
   * layout-effect cleanup, which React flushes first, so restoring here
   * lands last and wins.
   *
   * Two destinations, and the second is the one that matters. If the row's
   * overflow button is still there — Cancel, or a delete that failed — focus
   * goes back to it. If it is gone, the row was deleted out from under the
   * dialog, and focus goes to the rail's first control rather than to
   * `<body>`, which is where Radix would leave it.
   */
  const openerRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(false);
  const confirmOpen = pendingDelete !== null;
  const pendingId = pendingDelete?.id ?? null;

  useEffect(() => {
    const root = rootRef.current;
    if (confirmOpen && !wasOpenRef.current && pendingId !== null) {
      openerRef.current =
        root?.querySelector<HTMLElement>(
          `[data-thread-row-menu="${CSS.escape(pendingId)}"]`,
        ) ?? null;
    }
    if (!confirmOpen && wasOpenRef.current) {
      const opener = openerRef.current;
      if (opener?.isConnected) opener.focus();
      else root?.querySelector<HTMLElement>("[data-thread-rail-new]")?.focus();
      openerRef.current = null;
    }
    wasOpenRef.current = confirmOpen;
  }, [confirmOpen, pendingId]);

  const alert: ReactNode = notice ? (
    <StatusBanner
      severity="critical"
      // 03 §2.2 row 4 designates this state as the rail's inline
      // `role="alert"`, and StatusBanner is the only component allowed to
      // emit one (03 §7.3 permits exactly one product-wide). Both ways in
      // are the user's own action: arriving at the workbench, or pressing
      // Retry.
      userTriggered
      sentence={notice.sentence}
      recovery={notice.recovery}
      actions={
        notice.onRetry && notice.retryLabel ? (
          <Button variant="secondary" onClick={notice.onRetry} data-thread-rail-retry="">
            {notice.retryLabel}
          </Button>
        ) : null
      }
      className="text-ui-sm"
    />
  ) : null;

  return (
    <ThreadRailFrame
      heading={THREAD_RAIL.heading}
      newThreadLabel={THREAD_RAIL.newThread}
      onNavigate={onNavigate}
      notice={alert}
      state={state}
      headingId={headingId}
      rootRef={rootRef}
      className={className}
      footer={
        canLoadMore ? (
          <Button
            variant="secondary"
            fullWidth
            busy={isLoadingMore}
            onClick={onLoadMore}
            data-thread-rail-more=""
          >
            {THREAD_RAIL.loadMore}
          </Button>
        ) : null
      }
    >
      {loading ? (
        <ThreadListSkeleton label={THREAD_RAIL.loading} labelledBy={headingId} />
      ) : threads.length === 0 ? (
        state === "error" ? null : (
          // Distinct from loading (no `aria-busy`, no reserved rows) and
          // from the error above it (which keeps its own alert). Criterion 5.
          <EmptyState body={THREAD_RAIL.empty} className="min-h-0 flex-1" />
        )
      ) : (
        <ul
          aria-labelledby={headingId}
          className="ew-thread-rail__list"
          data-thread-list=""
        >
          {threads.map((thread) => {
            const active = thread.id === activeConversationId;
            const live = active && Boolean(attachedJobId);
            const href = threadRowHref(thread.id, activeConversationId, attachedJobId);

            return (
              <li
                key={thread.id}
                className="ew-thread-row"
                data-thread-row={thread.id}
                data-thread-row-live={live ? "" : undefined}
              >
                <Link
                  href={href}
                  onClick={() => onNavigate?.(href)}
                  aria-current={active ? "page" : undefined}
                  className={cx("ew-thread-row__link", "ew-focusable")}
                  data-thread-row-link={thread.id}
                >
                  <span className="ew-thread-row__title">{thread.title}</span>
                  {live ? (
                    <StatusBadge severity="live" className="shrink-0 text-ui-xs">
                      {THREAD_ROW.live}
                    </StatusBadge>
                  ) : null}
                </Link>

                {/*
                  Seam S4 (criterion 8): rendered in every row, empty and
                  zero-height. No badge, no placeholder, no aria-label — a
                  named empty slot would be announced as an owner that does
                  not exist. MT-01 fills it with children; nothing before
                  MT-01 fills it with anything.
                */}
                <span className="ew-thread-row__owner" data-thread-owner-slot="" />

                <Menu
                  trigger={
                    <Button
                      iconOnly
                      variant="ghost"
                      aria-label={threadMenuLabel(thread.title)}
                      data-thread-row-menu={thread.id}
                      className="shrink-0"
                    >
                      <OverflowGlyph />
                    </Button>
                  }
                >
                  <MenuItem onSelect={() => onNavigate?.(href)}>
                    {THREAD_ROW.open}
                  </MenuItem>
                  <MenuSeparator />
                  <MenuItem tone="critical" onSelect={() => onDeleteRequest?.(thread)}>
                    {THREAD_ROW.delete}
                  </MenuItem>
                </Menu>
              </li>
            );
          })}
        </ul>
      )}

      {/*
        Mounted only while it is open, so the closed rail costs nothing and
        `pendingDelete` is the single source of truth for both the dialog and
        the sentence inside it.
      */}
      {pendingDelete ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) onDeleteCancel?.();
          }}
          copy={dialogCopy}
          closeLabel={dialogCopy.close}
          pending={deletePending}
          onConfirm={() => onDeleteConfirm?.()}
        />
      ) : null}
    </ThreadRailFrame>
  );
}
