"use client";
import { useEffect } from "react";
import { allowWorkspaceNavigation } from "./navigationGuard";
import type { NavigationAction } from "./navigationRuntime";
export const NAVIGATION_INTENT_KEY = "arxiv.workspace.navigation-intent.v1";

export const navigationState = {
  engine: null as ((action: NavigationAction) => void) | null,
  pending: null as NavigationAction[] | null,
  readerHistory: false,
};
function send(action: NavigationAction) {
  if (navigationState.engine) navigationState.engine(action);
  else (navigationState.pending ??= []).push(action);
}
export function requestWorkspaceNavigation(href: string, kind: "paper" | "route" = "route") {
  navigationState.readerHistory = false;
  if (!navigationState.engine) {
    const destination = new URL(href, location.href);
    if (destination.origin === location.origin && destination.pathname.startsWith("/workspace/")) {
      const top = window.matchMedia?.("(max-width: 767px)").matches ? window.scrollY : document.getElementById("main")?.scrollTop ?? window.scrollY;
      try { history.replaceState({ ...history.state, workspaceScroll: top }, "", location.href); } catch { /* History quotas do not block navigation. */ }
      try { sessionStorage.setItem(NAVIGATION_INTENT_KEY, JSON.stringify({ kind, path: destination.pathname, at: Date.now(), exactReader: destination.pathname.startsWith("/workspace/items/") && (destination.searchParams.has("entry") || Boolean(destination.hash)) })); } catch { /* Navigation remains usable without cosmetic storage. */ }
    }
  }
  send({ type: "request", href, kind, base: location.href });
}
export function navigateWorkspace(href: string, kind: "paper" | "route" = "route"): boolean {
  if (!allowWorkspaceNavigation(href)) return false;
  requestWorkspaceNavigation(href, kind);
  location.assign(href);
  return true;
}
export function requestPaperNavigation() { requestWorkspaceNavigation(location.href, "paper"); }
export function settleWorkspaceContent(target: HTMLElement, content?: HTMLElement, focus = false) {
  send({ type: "settle", target, content, focus });
}
export function settleReaderTarget(target: HTMLElement, focus = true, explicit = false) {
  if (navigationState.readerHistory && !explicit) return;
  if (explicit) navigationState.readerHistory = false;
  if (focus) { target.tabIndex = -1; target.focus({ preventScroll: true }); }
  send({ type: "reader", target, explicit });
}
/** Capture synchronously; the deferred engine replays requests in order, final intent wins. */
export function useWorkspaceNavigation(path: string) {
  useEffect(() => {
    let active = true;
    let dispose: (() => void) | undefined;
    const initialPaper = document.querySelector<HTMLElement>(".ws-focus")?.dataset.paperKey;
    const capture = (event: Event) => {
      if (event.type === "popstate") navigationState.readerHistory = true;
      else if (!navigationState.engine && (event.type === "submit" || event.target instanceof Element && event.target.closest("a[href]"))) {
        try { history.replaceState({ ...history.state, workspaceScroll: window.scrollY || document.getElementById("main")?.scrollTop || 0 }, "", location.href); } catch { /* Navigation remains available when history is restricted. */ }
      }
      if (!navigationState.engine && event.type === "submit" && event.target instanceof HTMLFormElement && event.target.matches(".ws-composer")) {
        const query = String(new FormData(event.target).get("q") ?? "").trim();
        if (query && !query.startsWith("/")) {
          try { sessionStorage.setItem(NAVIGATION_INTENT_KEY, JSON.stringify({ kind: "paper", path: "/workspace/radar", at: Date.now() })); } catch { /* Search still works without cosmetic restoration. */ }
        }
      }
      send({ type: "event", event, base: location.href, prevented: event.defaultPrevented });
    };
    const guardedCapture = (event: Event) => {
      const target = event.target;
      // Managed Composer submits record intent only after their shared veto succeeds.
      if (event.type === "submit" && target instanceof HTMLFormElement && target.hasAttribute("data-guarded-navigation")) return;
      const commit = () => { if (!event.defaultPrevented) capture(event); };
      target?.addEventListener(event.type, commit, { capture: true, once: true });
      // Native UI dispatch runs microtasks between listeners; clean up after dispatch.
      setTimeout(() => target?.removeEventListener(event.type, commit, true), 0);
    };
    document.addEventListener("click", guardedCapture, true);
    document.addEventListener("submit", guardedCapture, true);
    window.addEventListener("popstate", capture, true);
    void import("./navigationRuntime").then(runtime => {
      if (active) dispose = runtime.mountWorkspaceNavigation(initialPaper);
    });
    return () => {
      active = false;
      document.removeEventListener("click", guardedCapture, true);
      document.removeEventListener("submit", guardedCapture, true);
      window.removeEventListener("popstate", capture, true);
      dispose?.();
    };
  }, [path]);
}
