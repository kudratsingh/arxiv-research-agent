"use client";

/**
 * WorkbenchShell — the `(workspace)` layout (WO-08).
 *
 * THE ONE THING THIS FILE EXISTS FOR. `landmark-one-main` and `region` fail
 * in **12 of 12** Gate 1 axe reports, because the shell it replaces
 * (`components/ConversationsShell.tsx`) is a `flex h-screen` div with no
 * landmarks at all. This module renders exactly one `<main id="main">`, and
 * puts every other pixel inside `header` / `nav[aria-label]`. That is
 * criterion 1, and it is the whole reason 05-MIGRATION.md §1.4 refuses to
 * split M1: "A half-migrated shell cannot satisfy `landmark-one-main`
 * (there would be two mains or none)".
 *
 * THE SECOND THING: the mobile repair (04 §8.3, 03 §7.5, RC-13). The old
 * shell put a 256px `w-64 shrink-0` rail beside the content at EVERY
 * viewport, and gave the content column `flex-1` with no `min-w-0`. At the
 * 412px audit width that leaves ~108px of work surface and a page that pans
 * horizontally. Both causes are structural, so both fixes are structural:
 *
 *   - CSS Grid with `minmax(0, 1fr)` on the content column, which removes
 *     the min-content floor by construction — the thing flex cannot do.
 *   - `min-width: 0` on `main` in every mode.
 *   - Below 768px the rail is not rendered at all. Not hidden: absent.
 *
 * Both live in ./workbench.css, where a reviewer can read them as rules
 * rather than as three responsive class strings.
 *
 * THREE MODES (RC-04), and why JavaScript decides which:
 *
 *   | Width      | Mode       | Rail                                      |
 *   |------------|------------|-------------------------------------------|
 *   | < 768px    | `drawer`   | Absent. A labelled header button opens it |
 *   |            |            | as an APG modal dialog.                   |
 *   | 768–1023px | `compact`  | A 56px icon strip. It expands over the    |
 *   |            |            | content, on demand, as the same drawer.   |
 *   | ≥ 1024px   | `expanded` | 260px, persistent, with a collapse toggle |
 *   |            |            | persisted to RAIL_COLLAPSED_STORAGE_KEY.  |
 *
 * The *widths* are CSS's (a media query in workbench.css). What JavaScript
 * decides is *which element exists*: rendering the rail below 768px and
 * hiding it with `display: none` would keep the legacy sidebar's
 * `GET /conversations` and its whole subtree in the tree at the exact width
 * where the repair is supposed to remove it, and would give the drawer a
 * second copy of the same list. `useSyncExternalStore` over `matchMedia` is
 * how that decision is made without a hydration mismatch: the server
 * snapshot is `expanded`, which is what the CSS paints at desktop widths
 * anyway, and the client snapshot replaces it during hydration.
 *
 * WHAT THIS FILE DOES NOT DO. It does not restyle, rewrite or even read the
 * feature components it renders. `ConversationSidebar`, `ConversationThread`
 * and `QueryForm` come through untouched — 05-MIGRATION.md §1.4's blast
 * radius argument depends on that, and it is what keeps the existing tests
 * green through M1. Their replacements are WO-13/14/16/20.
 *
 * SEAMS FOR THE WORK ORDERS THAT LAND INSIDE THIS SHELL:
 *
 *   - `WORKBENCH_COMPOSER_SLOT_ID` — the reserved, sticky bottom row of
 *     `main` (criterion 7). Empty in M1; WO-13's QueryComposer and WO-20's
 *     page composition render into it.
 *   - `<IdentitySlot />` — seam S4, returns `null` (criterion 9).
 *   - `rail`, `railMode`, `railCollapsed`, `defaultDrawerOpen`, `offline`
 *     make every state in 03 §4.1 reachable by passing props, which is what
 *     lets the stories cover them without a viewport or a network.
 *   - WO-09's recovery surfaces (`not-found.tsx`, `error.tsx`,
 *     `loading.tsx`) render as `children`, inside `main`, and therefore
 *     inherit the landmark structure and the `h1` position for free.
 *
 * WO-21 HOOKS. The shell publishes its state as data attributes so the
 * Playwright harness can assert a mode rather than infer one from pixel
 * widths: `data-workbench-shell`, `data-rail-mode`, `data-rail-collapsed`,
 * `data-workbench-offline`, and `data-workbench-region="composer"`.
 */

import Link from "next/link";
import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { ThemeToggle } from "@/components/patterns/ThemeToggle";
import { Button } from "@/components/primitives/Button";
import { SkipLink } from "@/components/primitives/SkipLink";
import { SHELL } from "@/lib/copy/shell";
import { THREAD_RAIL, WORKSPACE } from "@/lib/copy/threads";
import { RAIL_COLLAPSED_STORAGE_KEY } from "@/lib/tokens";

import { IdentitySlot } from "./IdentitySlot";
import "./workbench.css";

/**
 * The drawer is behind `React.lazy` for a measured reason, not a stylistic
 * one: statically importing the Dialog primitive into `/`'s module graph
 * adds 13,792 B gzip of first-load JavaScript and breaches RC-01's
 * 148,480 B ceiling by itself. `lazy` rather than `next/dynamic` because
 * the two produce the same async chunk and only one of them is a Next
 * runtime import that the unit project would have to stand in for.
 */
const ThreadDrawer = lazy(() => import("@/components/features/ThreadDrawer"));

/**
 * The workspace indicator, as WO-12's dictionary states it (criterion 9).
 *
 * 03-DESIGN-BRIEF.md §6 writes it as one sentence — "Shared workspace —
 * everyone with access to this deployment sees these threads." — and
 * `lib/copy/threads.ts` splits it into a lead and a detail so the lead can
 * hold a 320px header without the qualification being truncated away. Both
 * halves are always rendered: the qualification is the honest part, and the
 * shell does not get to choose between them (seam S6).
 *
 * The header renders them as two nodes so the lead can carry emphasis. This
 * constant is the same sentence as one string, for the tests that assert
 * §6's wording and for any later surface that needs it whole.
 */
export const WORKSPACE_INDICATOR = `${WORKSPACE.indicator} — ${WORKSPACE.indicatorDetail}`;

/**
 * The reserved composer slot's id. WO-13 and WO-20 render into it; it is
 * the bottom row of `main`'s grid, so it never scrolls away, and below
 * 768px it carries `env(safe-area-inset-bottom)` (criterion 7).
 */
export const WORKBENCH_COMPOSER_SLOT_ID = "workbench-composer";

/** The id `<main>` carries, and therefore the id `SkipLink` points at. */
export const MAIN_ID = "main";

/** The rail's id, so the collapse toggle can name what it controls. */
export const RAIL_ID = "workbench-rail";

export type RailMode = "drawer" | "compact" | "expanded";

/**
 * The two breakpoints, as media query strings. They are
 * `--layout-breakpoint-md` and `--layout-breakpoint-lg` in app/tokens.css;
 * web/tests/shell/layout.test.ts asserts these strings against the token
 * values and against workbench.css, so the three copies cannot drift.
 */
export const COMPACT_QUERY = "(min-width: 768px)";
export const EXPANDED_QUERY = "(min-width: 1024px)";

/* =========================================================================
 * Stores
 *
 * Three `useSyncExternalStore` sources. All three share the same shape and
 * the same reason for it: each has a value the server cannot know, and
 * reading it in an effect would paint one frame of the wrong layout first.
 * ========================================================================= */

function noopSubscribe(): () => void {
  return () => {};
}

function mediaSubscribe(onStoreChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return noopSubscribe();
  const queries = [window.matchMedia(COMPACT_QUERY), window.matchMedia(EXPANDED_QUERY)];
  const attached = queries.filter((query) => typeof query.addEventListener === "function");
  for (const query of attached) query.addEventListener("change", onStoreChange);
  return () => {
    for (const query of attached) query.removeEventListener("change", onStoreChange);
  };
}

/** The mode the current viewport is in. */
export function readRailMode(): RailMode {
  if (typeof window === "undefined" || !window.matchMedia) return "expanded";
  if (window.matchMedia(EXPANDED_QUERY).matches) return "expanded";
  if (window.matchMedia(COMPACT_QUERY).matches) return "compact";
  return "drawer";
}

/**
 * `expanded` on the server. A server render has no viewport, and this is
 * the mode whose CSS the other two override rather than the other way
 * round, so a narrow client corrects it during hydration without ever
 * painting a rail (workbench.css hides `.ew-shell__rail` below 768px
 * regardless of what JavaScript thinks).
 */
export function serverRailMode(): RailMode {
  return "expanded";
}

/* ---- The persisted collapse preference (RC-05's second key) ------------ */

const collapseListeners = new Set<() => void>();

function collapseSubscribe(onStoreChange: () => void): () => void {
  collapseListeners.add(onStoreChange);
  // `storage` fires in the OTHER tabs, which is exactly where a second
  // window of the same workbench needs to hear about it.
  if (typeof window !== "undefined") window.addEventListener("storage", onStoreChange);
  return () => {
    collapseListeners.delete(onStoreChange);
    if (typeof window !== "undefined") window.removeEventListener("storage", onStoreChange);
  };
}

/** `"1"` means collapsed. Anything else, including a throw, means expanded. */
export function readRailCollapsed(): boolean {
  try {
    return window.localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function serverRailCollapsed(): boolean {
  return false;
}

export function writeRailCollapsed(collapsed: boolean): void {
  try {
    window.localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, collapsed ? "1" : "0");
  } catch {
    /* Storage-blocked. RC-05: the preference is cosmetic and safely absent. */
  }
  for (const listener of collapseListeners) listener();
}

/* ---- Offline ----------------------------------------------------------- */

function offlineSubscribe(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") return noopSubscribe();
  window.addEventListener("online", onStoreChange);
  window.addEventListener("offline", onStoreChange);
  return () => {
    window.removeEventListener("online", onStoreChange);
    window.removeEventListener("offline", onStoreChange);
  };
}

export function readOffline(): boolean {
  if (typeof navigator === "undefined") return false;
  return navigator.onLine === false;
}

export function serverOffline(): boolean {
  return false;
}

/* =========================================================================
 * Icons
 *
 * Three 16×16 marks in `currentColor`, `aria-hidden`, drawn inline. Not
 * from components/primitives/marks.tsx: that module is the *status* mark
 * vocabulary of 03 §3.4, where the shape carries meaning beside a word.
 * These are decoration beside a name that is always present.
 * ========================================================================= */

function Glyph({ d }: { d: string }) {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16" width="16" height="16">
      <path d={d} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" fill="none" />
    </svg>
  );
}

const LIST_GLYPH = "M2.5 4h11M2.5 8h11M2.5 12h11";
const PLUS_GLYPH = "M8 3v10M3 8h10";
const COLLAPSE_GLYPH = "M10 3.5 5.5 8l4.5 4.5";
const EXPAND_GLYPH = "M6 3.5 10.5 8 6 12.5";

/* =========================================================================
 * The shell
 * ========================================================================= */

export interface WorkbenchShellProps {
  children: ReactNode;
  /**
   * The thread rail's contents. Required, and deliberately not defaulted to
   * `ConversationSidebar`: the shell is layout, and the one component in it
   * that fetches is `./ThreadRailBridge`, which the `(workspace)` layout
   * passes in. That is what lets every story and every test render the whole
   * shell with no network (04 §5.1).
   */
  rail: ReactNode;
  /** Overrides the viewport-derived mode. Stories and tests only. */
  railMode?: RailMode;
  /** Overrides the persisted collapse preference. Stories and tests only. */
  railCollapsed?: boolean;
  /** Opens the drawer on mount. Stories and tests only. */
  defaultDrawerOpen?: boolean;
  /** Overrides `navigator.onLine`. Stories and tests only. */
  offline?: boolean;
}

export function WorkbenchShell({
  children,
  rail,
  railMode,
  railCollapsed,
  defaultDrawerOpen = false,
  offline,
}: WorkbenchShellProps): React.ReactElement {
  const measuredMode = useSyncExternalStore(mediaSubscribe, readRailMode, serverRailMode);
  const measuredCollapsed = useSyncExternalStore(
    collapseSubscribe,
    readRailCollapsed,
    serverRailCollapsed,
  );
  const measuredOffline = useSyncExternalStore(offlineSubscribe, readOffline, serverOffline);

  const mode = railMode ?? measuredMode;
  // RC-04: the collapse toggle is "applied at ≥1024px only (below that,
  // collapsed *is* the default)". So the preference is read at `expanded`
  // and the two narrower modes are collapsed by definition.
  const collapsed = mode === "expanded" ? (railCollapsed ?? measuredCollapsed) : true;
  const isOffline = offline ?? measuredOffline;

  const [drawerOpen, setDrawerOpen] = useState(defaultDrawerOpen);
  // The drawer's module is only imported once it has been asked for, which
  // is what keeps Radix out of both routes' first-load chunk union.
  const [drawerRequested, setDrawerRequested] = useState(defaultDrawerOpen);

  /**
   * The control that opened the drawer, so focus can go back to it
   * (criterion 6).
   *
   * WHY THE SHELL DOES THIS AND NOT RADIX. `DialogContentModal` handles its
   * own `onCloseAutoFocus` by calling `preventDefault()` and then focusing
   * `Dialog.Trigger`'s ref — so a dialog opened by anything that is not a
   * `Dialog.Trigger` restores focus to nothing at all. This shell cannot
   * use `Dialog.Trigger`: the trigger has to live in the header, and the
   * header is not inside the drawer's lazily-imported module. Recording the
   * element that opened it is the version of "restore focus to the trigger"
   * that survives both of those facts — and it handles the second trigger
   * (the icon strip's) for free.
   */
  const triggerRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(false);

  const openDrawer = useCallback((event: { currentTarget: HTMLElement }) => {
    triggerRef.current = event.currentTarget;
    setDrawerRequested(true);
    setDrawerOpen(true);
  }, []);

  const onDrawerOpenChange = useCallback((next: boolean) => {
    setDrawerOpen(next);
  }, []);

  const toggleCollapsed = useCallback(() => {
    writeRailCollapsed(!readRailCollapsed());
  }, []);

  const railContent = rail;
  const showRail = mode !== "drawer";
  const showStrip = collapsed;
  // The drawer is only ever the *narrow* modes' rail. Deriving this rather
  // than closing it from an effect means a resize past 1024px cannot leave
  // the list mounted twice — once in the rail and once in the dialog —
  // which would be two `GET /conversations` and two copies of the same rows.
  const drawerVisible = drawerOpen && mode !== "expanded";

  // A passive effect, deliberately: Radix's own focus handling runs in a
  // layout-effect cleanup, which React flushes before this. Restoring here
  // therefore lands last and wins.
  useEffect(() => {
    if (wasOpenRef.current && !drawerVisible) triggerRef.current?.focus();
    wasOpenRef.current = drawerVisible;
  }, [drawerVisible]);

  return (
    <>
      {/*
        First in the tab order (criterion 10), and first in the DOM, which
        is what makes that true without a `tabindex`. It points at
        `#main` — SkipLink's own default — and axe's `region` rule exempts a
        skip link from needing a landmark of its own.
      */}
      <SkipLink targetId={MAIN_ID}>{WORKSPACE.skipToContent}</SkipLink>

      <div
        className="ew-shell"
        data-workbench-shell=""
        data-rail-mode={mode}
        data-rail-collapsed={String(collapsed)}
        data-workbench-offline={isOffline ? "" : undefined}
      >
        <header className="ew-shell__header">
          {/*
            Criterion 6: "the trigger is a labelled header button, never
            hover-only". It is a real `<button>` with a visible word, in the
            header, at every width where the rail is not persistent.
          */}
          {mode === "drawer" ? (
            <Button
              variant="secondary"
              onClick={openDrawer}
              aria-haspopup="dialog"
              aria-expanded={drawerVisible}
              data-drawer-trigger=""
            >
              <Glyph d={LIST_GLYPH} />
              {THREAD_RAIL.openDrawer}
            </Button>
          ) : null}

          <p className="ew-shell__workspace">
            <strong className="font-medium text-ink">{WORKSPACE.indicator}</strong>{" "}
            {WORKSPACE.indicatorDetail}
          </p>

          <div className="ew-shell__actions">
            {/*
              Not a live region. 03 §7.3 allows exactly two product-wide —
              one `role="status"` and one `role="alert"` — and both are
              spoken for. WO-12's StatusBanner is what will announce this;
              the shell only states it.
            */}
            {isOffline ? (
              <span className="text-ui-xs font-medium text-critical-text">
                {SHELL.offline}
              </span>
            ) : null}
            <ThemeToggle />
            <IdentitySlot />
          </div>
        </header>

        {showRail ? (
          <nav id={RAIL_ID} aria-label={THREAD_RAIL.heading} className="ew-shell__rail">
            {showStrip ? (
              <div className="ew-shell__strip">
                {/*
                  The 56px icon strip (criterion 3). Every control in it has
                  an accessible name, because an icon strip whose controls
                  are unnamed is the `button-name` violation this redesign
                  exists to stop shipping.
                */}
                <Link
                  href="/"
                  aria-label={SHELL.newQuestion}
                  className="ew-focusable ew-target ew-target--sm inline-flex items-center justify-center rounded-md text-ink-muted hover:bg-sunken hover:text-ink"
                >
                  <Glyph d={PLUS_GLYPH} />
                </Link>

                {mode === "expanded" ? (
                  <Button
                    variant="ghost"
                    iconOnly
                    aria-label={THREAD_RAIL.expand}
                    aria-expanded={false}
                    aria-controls={RAIL_ID}
                    onClick={toggleCollapsed}
                    data-rail-collapse-toggle=""
                  >
                    <Glyph d={EXPAND_GLYPH} />
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    iconOnly
                    aria-label={THREAD_RAIL.openDrawer}
                    aria-haspopup="dialog"
                    aria-expanded={drawerVisible}
                    onClick={openDrawer}
                    data-drawer-trigger=""
                  >
                    <Glyph d={LIST_GLYPH} />
                  </Button>
                )}
              </div>
            ) : (
              <div className="flex h-full min-h-0 flex-col">
                <div className="flex justify-end px-2 pt-2">
                  <Button
                    variant="ghost"
                    iconOnly
                    aria-label={THREAD_RAIL.collapse}
                    aria-expanded={true}
                    aria-controls={RAIL_ID}
                    onClick={toggleCollapsed}
                    data-rail-collapse-toggle=""
                  >
                    <Glyph d={COLLAPSE_GLYPH} />
                  </Button>
                </div>
                <div className="min-h-0 flex-1">{railContent}</div>
              </div>
            )}
          </nav>
        ) : null}

        {/*
          Exactly one `<main id="main">` per document (criterion 1). The
          route's own subtree — landing composer, thread, or one of WO-09's
          recovery surfaces — renders into `.ew-shell__surface`.
        */}
        <main id={MAIN_ID} aria-label={WORKSPACE.mainLandmark} className="ew-shell__main">
          <div className="ew-shell__surface">{children}</div>
          <div
            id={WORKBENCH_COMPOSER_SLOT_ID}
            className="ew-shell__composer"
            data-workbench-region="composer"
          />
        </main>
      </div>

      {drawerRequested ? (
        <Suspense fallback={null}>
          <ThreadDrawer open={drawerVisible} onOpenChange={onDrawerOpenChange}>
            {railContent}
          </ThreadDrawer>
        </Suspense>
      ) : null}
    </>
  );
}
