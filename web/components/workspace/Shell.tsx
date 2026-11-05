"use client";
import { loadContextReadouts } from "./contextModules";


import Link from "next/link";
import { useWorkspaceNavigation } from "@/lib/workspace/navigation";
import { usePathname } from "next/navigation";
import { lazy, Suspense, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { dispatchWorkspaceCommand } from "@/lib/workspace/dispatch";
import type { WorkspaceDialogRequest } from "./WorkspaceDialogs";
import { SkipLink } from "@/components/primitives/SkipLink";
import { Icon, type IconName } from "./Icon";
import { Mascot } from "./Mascot";
import { WorkspaceSlots } from "./Slots";
import { useSyntheticPreview } from "./PreviewContext";
import { useWorkspaceShortcuts } from "./useWorkspaceShortcuts";
import { setSidebarCollapsed, useSidebarPreference, useSidebarViewport } from "./useSidebarPreference";
import "@/components/daily/daily.css";
import "./controller.css";
import { ThemeToggle } from "@/components/patterns/ThemeToggle";
import { ModeSwitch } from "./ModeSwitch";
import { contextHref, useProductContext } from "@/lib/workspace/productContext";

const Composer = lazy(() => import("./Composer").then(composer => ({ default: composer.Composer })));
const WorkspaceDialogs = lazy(() => import("./WorkspaceDialogs"));
const ProjectSelector = lazy(() => loadContextReadouts().then(module => ({ default: module.ProjectSelector })));

const NAVIGATION: readonly [string, string, IconName, string][] = [
  ["today", "Today", "today", "T"], ["radar", "Radar", "radar", "R"],
  ["library", "Library", "library", "L"], ["interests", "Interests", "interests", "I"],
  ["operations", "Sources & checks", "sources", "S"], ["review", "Review", "review", "V"],
];
const FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex="-1"])';

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const context = useProductContext();
  const syntheticPreview = useSyntheticPreview();
  const viewport = useSidebarViewport();
  const collapsed = useSidebarPreference();
  const [open, setOpen] = useState(false);
  const [dialog, setDialog] = useState<WorkspaceDialogRequest | null>(null);
  const [sidebarNode, setSidebarNode] = useState<HTMLDivElement | null>(null);
  const [headerNode, setHeaderNode] = useState<HTMLDivElement | null>(null);
  const [barNode, setBarNode] = useState<HTMLDivElement | null>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const drawerId = useId();
  const mobile = viewport === "mobile";
  const overlayOpen = viewport !== "desktop" && open;
  const rail = viewport === "tablet" ? !open : viewport === "desktop" && collapsed;
  const drawerHidden = mobile && !open;
  const route = NAVIGATION.find(([slug]) => path.startsWith(`/workspace/${slug}`))?.[1] ?? (path.startsWith("/workspace/projects") ? "Projects" : path.startsWith("/workspace/threads/") ? "Learning thread" : "Reader");
  const projectControl = context.mode === "research" && <Suspense fallback={<p className="daily-muted" aria-busy="true">Opening project controls…</p>}><ProjectSelector /></Suspense>;
  useWorkspaceShortcuts();
  useWorkspaceNavigation(path);

  // App Router may restore the mounted template from its navigation cache.
  // History navigation must dismiss an overlay before restoring page content.
  useEffect(() => {
    const closeOnHistory = () => setOpen(false);
    window.addEventListener("popstate", closeOnHistory);
    return () => window.removeEventListener("popstate", closeOnHistory);
  }, []);

  useEffect(() => {
    if (!overlayOpen) return;
    const surface = mobile ? drawerRef.current : sidebarRef.current;
    const toggleButton = toggleRef.current;
    closeRef.current?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.isComposing || event.key === "Tab" && (event.ctrlKey || event.metaKey || event.altKey)) return;
      if (event.target instanceof Element && event.target.closest(".ws-command-dialog")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
      }
      if (event.key !== "Tab" || !surface) return;
      const controls = Array.from(surface.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((node) => {
        if (node.closest("[hidden], [inert]") || node.tabIndex < 0 ||
          getComputedStyle(node).display === "none" || getComputedStyle(node).visibility === "hidden") return false;
        if (node instanceof HTMLInputElement && node.type === "radio" && node.name) {
          const group = Array.from(surface.querySelectorAll<HTMLInputElement>('input[type="radio"]')).filter((radio) => radio.name === node.name);
          return group.some((radio) => radio.checked) ? node.checked : group[0] === node;
        }
        return true;
      });
      const first = controls[0], last = controls[controls.length - 1];
      if (!first || !last) { event.preventDefault(); surface.focus(); return; }
      if (event.shiftKey && (document.activeElement === first || !surface.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !surface.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      document.removeEventListener("keydown", trap);
      toggleButton?.focus();
    };
  }, [overlayOpen, mobile]);

  function showDialog(kind: "palette" | "shortcuts") {
    setDialog({ kind, invoker: document.activeElement instanceof HTMLElement ? document.activeElement : null });
  }
  function toggle() {
    if (viewport === "desktop") setSidebarCollapsed(!collapsed);
    else setOpen(!open);
  }
  function cycleTheme() {
    const radios = Array.from(sidebarRef.current!.querySelectorAll<HTMLInputElement>('input[name="theme-preference"]'));
    const current = radios.findIndex((radio) => radio.checked);
    radios[(current + 1) % radios.length]?.click();
  }

  return <WorkspaceSlots sidebar={sidebarNode} header={headerNode} bar={barNode}>
    <div className="daily-app workspace-app ws-app font-ui" data-workspace-path={path} data-viewport={viewport} data-rail={rail} data-drawer={overlayOpen ? "open" : "closed"}>
      <SkipLink />
      <span className="sr-only" data-workspace-announcement="" aria-live="polite" aria-atomic="true" />
      {overlayOpen && <div className="ws-scrim" aria-hidden="true" onClick={() => setOpen(false)} />}
      <aside ref={sidebarRef} className="ws-sidebar" aria-label="Workspace controls"
        role={overlayOpen && !mobile ? "dialog" : undefined} aria-modal={overlayOpen && !mobile ? true : undefined} tabIndex={-1}>
        <div className="ws-brand-row" inert={mobile && overlayOpen}>
          <Link href={contextHref("/workspace/today", context)} prefetch={false} scroll={false} className="ws-brand" title="Research workspace · Jazzy">
            <Mascot /><span className="ws-brand-name">Research workspace</span>
          </Link>
          <button ref={toggleRef} className="ws-sidebar-toggle" type="button" data-command="toggle-sidebar"
            aria-label={mobile ? "Queue & controls" : rail ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={mobile ? open : !rail} aria-controls={drawerId} aria-keyshortcuts="[" onClick={toggle}>
            <Icon name={mobile ? "menu" : "sidebar"} /><span className="ws-toggle-label">Queue & controls</span>
          </button>
          <button type="button" className="ws-theme-cycle" aria-label="Cycle color theme" onClick={cycleTheme}><Icon name="theme" /></button>
        </div>
        <div className="ws-mode-sidebar" inert={mobile || rail}><ModeSwitch path={path} />{!mobile && !rail && projectControl}</div>
        <nav className="ws-navigation" aria-label="Research workspace" inert={mobile && overlayOpen}>
          {NAVIGATION.map(([slug, label, icon, shortcut]) => <Link key={slug} data-workspace-route={`/workspace/${slug}`} href={contextHref(`/workspace/${slug}`, context)} prefetch={false} scroll={false}
            title={label} aria-label={label} aria-current={path.startsWith(`/workspace/${slug}`) ? "page" : undefined}>
            <Icon name={icon} /><span className="ws-nav-label">{label}</span><kbd aria-hidden="true">G {shortcut}</kbd>
          </Link>)}
        </nav>
        <div ref={drawerRef} id={drawerId} className="ws-drawer" hidden={drawerHidden}
          role={mobile && overlayOpen ? "dialog" : undefined} aria-modal={mobile && overlayOpen ? true : undefined}
          aria-label={mobile && overlayOpen ? "Queue & controls" : undefined} tabIndex={-1}>
          {overlayOpen && <button ref={closeRef} type="button" className="ws-drawer-close" data-command="escape" onClick={() => setOpen(false)}>
            <Icon name="dismiss" />Close controls
          </button>}
          <div ref={setSidebarNode} className="ws-sidebar-slot" />
          <footer className="ws-sidebar-footer" hidden={rail}>
            <a href="/api/workspace/export" download="research-notes.md">Export notes as Markdown ↗</a>
            <Link href="/today" prefetch={false}>Fictional preview ↗</Link>
            <Link href="/" prefetch={false}>Research a question ↗</Link>
            <button type="button" className="ws-sidebar-toggle ws-shortcuts-button" data-command="shortcuts" aria-keyshortcuts="?" onClick={() => showDialog("shortcuts")}>Keyboard shortcuts <kbd aria-hidden="true">?</kbd></button>
            <ThemeToggle />
            <p className="ws-storage">Notes belong to your local account. A failed save stays a draft; it is never labelled saved.</p>
          </footer>
        </div>
      </aside>
      <main id="main" tabIndex={-1} className="daily-main ws-stage" inert={overlayOpen}>
        <header className="ws-stage-header">
          <div className="ws-mode-heading"><ModeSwitch path={path} />{(mobile || rail) && projectControl}</div>
          <div className="ws-stage-topline"><span className="ws-breadcrumb">workspace <span aria-hidden="true">›</span> {route.toLowerCase()}</span><div ref={setHeaderNode} className="ws-header-slot" /></div>
          <div className="ws-status-line">{syntheticPreview
            ? <><strong>Design preview · synthetic sample papers</strong><span>Sample source checks · private server saves · generation off</span></>
            : <><strong>Local workspace</strong><span>Real source metadata · private server saves · generation off</span></>}<button type="button" className="ws-sidebar-toggle ws-palette-trigger" data-command="command-palette" aria-label="Open command palette" aria-keyshortcuts="Meta+K Control+K" onClick={() => showDialog("palette")}><kbd aria-hidden="true">⌘K</kbd><span>Commands</span></button></div>
        </header>
        {children}
        <div className="ws-bar"><Suspense fallback={<div className="ws-composer" aria-busy="true"><button type="button" className="ws-composer-toggle" disabled>Opening search…</button></div>}><Composer /></Suspense><div ref={setBarNode} className="ws-bar-slot" /></div>
      </main>
      {dialog && <Suspense fallback={null}><WorkspaceDialogs onCommand={dispatchWorkspaceCommand} request={dialog} onClose={() => setDialog(null)} /></Suspense>}
    </div>
  </WorkspaceSlots>;
}
