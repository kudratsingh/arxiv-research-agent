import { navigationState as bridge } from "./navigation";

export type NavigationAction =
  | { type: "request"; href: string; kind: "paper" | "route"; base: string }
  | { type: "settle"; target: HTMLElement; content?: HTMLElement; focus: boolean }
  | { type: "reader"; target: HTMLElement; explicit: boolean }
  | { type: "event"; event: Event; base: string; prevented: boolean };
type Intent = { exactReader?: boolean; kind: "paper" | "route" | "history"; path: string; at: number; top?: number };
const INTENT_KEY = "arxiv.workspace.navigation-intent.v1";
const state = { intent: null as Intent | null };
function clearIntent() {
  state.intent = null;
  try { sessionStorage.removeItem(INTENT_KEY); } catch { /* Cosmetic navigation works without storage. */ }
}
const HISTORY_KEY = "workspaceScroll";
let generation = 0;
let frame = 0;
let animation: Animation | null = null;
function cancel() {
  generation += 1;
  cancelAnimationFrame(frame);
  animation?.cancel(); animation = null;
}
function mobile() { return window.matchMedia?.("(max-width: 767px)").matches ?? false; }
function stage() {
  return Array.from(document.querySelectorAll<HTMLElement>("main.ws-stage"))
    .findLast(main => main.closest<HTMLElement>(".ws-app")?.dataset.workspacePath === location.pathname);
}
function scrollTop() { return mobile() ? window.scrollY : stage()?.scrollTop ?? window.scrollY; }
function writeTop(top: number) {
  const container = stage();
  if (!container) return;
  // A short paper still needs room to place its heading at the same inset.
  // Recompute against natural content every time; never accumulate old reserve.
  container.querySelector("[data-workspace-scroll-tail]")?.remove();
  const viewport = mobile() ? document.documentElement : container;
  const maximum = Math.max(0, viewport.scrollHeight - (mobile() ? window.innerHeight : container.clientHeight));
  if (top > maximum) {
    const tail = document.createElement("div");
    tail.dataset.workspaceScrollTail = "";
    tail.setAttribute("aria-hidden", "true");
    tail.style.height = `${Math.ceil(top - maximum)}px`;
    container.append(tail);
  }
  if (!mobile()) container.scrollTo?.({ top, behavior: "instant" });
  else window.scrollTo({ top, behavior: "instant" });
}
/** Scroll first, then animate only the content. Superseded work cannot move the viewport. */
export function settleWorkspaceContent(target: HTMLElement, content?: HTMLElement, focus = false) {
  cancel();
  const ownGeneration = generation;
  frame = requestAnimationFrame(() => {
    if (ownGeneration !== generation || !target.isConnected) return;
    const container = stage();
    const offset = !mobile() && container ? container.getBoundingClientRect().top : 0;
    writeTop(Math.max(0, scrollTop() + target.getBoundingClientRect().top - offset - 16));
    if (focus) { target.tabIndex = -1; target.focus({ preventScroll: true }); }
    clearIntent();
    const message = content?.dataset.paperAnnouncement;
    const live = document.querySelector("[data-workspace-announcement]");
    if (message && live && live.textContent !== message) live.textContent = message;
    frame = requestAnimationFrame(() => {
      if (ownGeneration !== generation || !content?.isConnected || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
      animation = content.animate?.([{ opacity: .55, transform: "translateY(6px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 170, easing: "ease-out" }) ?? null;
    });
  });
}


export function mountWorkspaceNavigation(initialPaper?: string) {
    let previousPaper = initialPaper;
    if (!state.intent) {
      try {
        const stored = JSON.parse(sessionStorage.getItem(INTENT_KEY) ?? "null") as Intent | null;
        if (stored && ["route", "paper"].includes(stored.kind) && stored.path === location.pathname && Date.now() - stored.at < 10_000) state.intent = stored;
      } catch { /* Malformed or unavailable cosmetic navigation storage is ignored. */ }
    }
    // A Next template replacement may finish before its new popstate listener
    // attaches. The browser entry remains the authority in that mount gap.
    if ((!state.intent || state.intent.path !== location.pathname) && typeof history.state?.workspaceScroll === "number") {
      clearIntent();
      bridge.readerHistory = true;
      state.intent = { kind: "history", path: location.pathname, at: Date.now(), top: history.state.workspaceScroll };
    }
    const explicitFragment = () => location.pathname.startsWith("/workspace/items/") && Boolean(location.hash) && typeof history.state?.workspaceScroll !== "number";
    const releaseFragment = () => {
      if (!explicitFragment()) return;
      cancel(); bridge.readerHistory = false;
      state.intent = { kind: "route", exactReader: true, path: location.pathname, at: Date.now() };
    };
    releaseFragment();
    let restoreFrame = 0;
    let checkpointTimer: ReturnType<typeof setTimeout> | undefined;
    const ready = () => {
      const paper = stage()?.querySelector<HTMLElement>(".ws-focus");
      const key = paper?.dataset.paperKey;
      const changed = previousPaper !== undefined && key !== undefined && previousPaper !== key;
      if (key !== undefined) previousPaper = key;
      if (!state.intent) {
        if (changed && paper) settleWorkspaceContent(paper.querySelector<HTMLElement>(".ws-focus-heading") ?? paper, paper);
        return;
      }
      if (state.intent.path !== location.pathname) return;
      const main = stage();
      const heading = main?.querySelector<HTMLElement>("h1");
      const listRoute = location.pathname.match(/^\/workspace\/(today|radar|library)$/)?.[1];
      if (!main || !heading || main.querySelector('[aria-busy="true"]') || listRoute && !main.querySelector(`.ws-${listRoute}`)) return;
      if (state.intent.kind === "paper") {
        const paper = main.querySelector<HTMLElement>(".ws-focus");
        if (paper) settleWorkspaceContent(paper.querySelector<HTMLElement>(".ws-focus-heading") ?? paper, paper);
        else {
          const empty = main.querySelector<HTMLElement>(".daily-empty h2, .ws-radar-state h2");
          if (empty) settleWorkspaceContent(empty);
        }
        return;
      }
      if (state.intent.kind === "history") {
        const pending = state.intent;
        cancelAnimationFrame(restoreFrame);
        restoreFrame = requestAnimationFrame(() => {
          if (state.intent !== pending || stage() !== main || !heading.isConnected || main.querySelector('[aria-busy="true"]')) return;
          if (pending.top !== undefined) writeTop(pending.top);
          clearIntent();
        });
        return;
      }
      const query = new URLSearchParams(location.search);
      if (state.intent.exactReader || location.pathname.startsWith("/workspace/items/") && (query.has("entry") || location.hash)) {
        // A missed popstate may have suppressed Reader's first effect. Honor its
        // rendered exact target; material spans still resolve in RetainedSource.
        let fragment = "";
        try { fragment = decodeURIComponent(location.hash.slice(1)); } catch { /* Invalid fragments never invent a target. */ }
        const entry = query.get("entry");
        const target = entry ? document.getElementById(`workspace-entry-${entry}`)
          : /^(abstract|excerpt|full_text):/.test(fragment) ? (main.querySelector<HTMLElement>("#source-anchor") ?? main.querySelector<HTMLElement>("#source"))
          : ["source", "notes", "understand"].includes(fragment) ? document.getElementById(fragment) : null;
        if (target) settleWorkspaceContent(target);
        else clearIntent();
        return;
      }
      settleWorkspaceContent(heading, undefined, true);
    };
    const fragmentChanged = () => { releaseFragment(); ready(); };
    window.addEventListener("hashchange", fragmentChanged, true);
    const observer = new MutationObserver(ready);
    // Next templates can replace main while a cached route is opening. Observe
    // the stable document host, not a detached previous route's main element.
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-paper-key", "data-workspace-path", "aria-busy"] });
    const savePosition = () => {
      if (state.intent) return;
      const url = location.href, top = scrollTop();
      clearTimeout(checkpointTimer);
      checkpointTimer = setTimeout(() => {
        if (state.intent || location.href !== url) return;
        try { history.replaceState({ ...history.state, [HISTORY_KEY]: top }, "", url); } catch { /* Browser history limits do not disable reading. */ }
      }, 150);
    };
    const captureScroll = (event: Event) => { if (event.target === stage()) savePosition(); };
    window.addEventListener("scroll", savePosition, { passive: true });
    document.addEventListener("scroll", captureScroll, { passive: true, capture: true });
    const checkpoint = () => {
      try { history.replaceState({ ...history.state, [HISTORY_KEY]: scrollTop() }, "", location.href); } catch { /* History quotas must not block navigation. */ }
    };
    const request = (href: string, kind: "paper" | "route", base: string) => {
      if (!base) return;
      const url = new URL(href, base);
      if (url.origin !== new URL(base).origin || !url.pathname.startsWith("/workspace/")) return;
      if (base === location.href) checkpoint();
      cancel(); bridge.readerHistory = false;
      state.intent = { kind, path: url.pathname, at: Date.now(), exactReader: url.pathname.startsWith("/workspace/items/") && (url.searchParams.has("entry") || Boolean(url.hash)) };
      try { sessionStorage.setItem(INTENT_KEY, JSON.stringify(state.intent)); } catch { /* Memory retains the request. */ }
    };
    const ownedEngine = (action: NavigationAction) => {
      if (action.type === "request") request(action.href, action.kind, action.base);
      else if (action.type === "settle") { settleWorkspaceContent(action.target, action.content, action.focus); return; }
      else if (action.type === "reader") {
        if (action.explicit) clearIntent();
        settleWorkspaceContent(action.target); return;
      } else {
        const { event, base, prevented } = action;
        if (event.type === "popstate") {
          cancel();
          const top = (event as PopStateEvent).state?.workspaceScroll;
          state.intent = { kind: "history", path: new URL(base).pathname, at: Date.now(), top: typeof top === "number" ? top : undefined };
          releaseFragment();
        } else if (event.type === "click") {
          const mouse = event as MouseEvent;
          if (prevented || mouse.button !== 0 || mouse.metaKey || mouse.ctrlKey || mouse.shiftKey || mouse.altKey) return;
          const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
          if (!link || link.target === "_blank" || link.hasAttribute("download") || link.getAttribute("href")?.startsWith("#")) return;
          const destination = new URL(link.href);
          const returning = new URL(base).pathname.startsWith("/workspace/items/") && ["/workspace/today", "/workspace/radar", "/workspace/library"].includes(destination.pathname);
          request(link.href, returning ? "paper" : "route", base);
        } else {
          const form = event.target;
          if (!(form instanceof HTMLFormElement) || !form.matches(".ws-composer")) return;
          const query = new FormData(form).get("q");
          if (typeof query !== "string" || !query.trim() || query.trim().startsWith("/")) return;
          request("/workspace/radar", "paper", base);
        }
      }
      ready();
    };
    bridge.engine = ownedEngine;
    const queued = bridge.pending; bridge.pending = null;
    queued?.forEach(ownedEngine);
    ready();
    return () => {
      if (bridge.engine === ownedEngine) { cancel(); bridge.engine = null; }
      window.removeEventListener("hashchange", fragmentChanged, true);
      observer.disconnect(); cancelAnimationFrame(restoreFrame); clearTimeout(checkpointTimer);
      window.removeEventListener("scroll", savePosition); document.removeEventListener("scroll", captureScroll, true);
    };
}
