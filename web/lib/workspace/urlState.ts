"use client";

import { useSyncExternalStore } from "react";

export const WORKSPACE_URL_EVENT = "workspace:url";

function subscribe(listener: () => void) {
  window.addEventListener("popstate", listener);
  window.addEventListener(WORKSPACE_URL_EVENT, listener);
  return () => {
    window.removeEventListener("popstate", listener);
    window.removeEventListener(WORKSPACE_URL_EVENT, listener);
  };
}

/** Stable SSR snapshot; the client reads its actual URL after hydration. */
export function serverQueryParam(): null { return null; }

export function useQueryParam(name: string): string | null {
  return useSyncExternalStore(subscribe,
    () => new URLSearchParams(window.location.search).get(name), serverQueryParam);
}

/** Local selection replaces history by default; filters may explicitly push. */
export function setQueryParam(name: string, value: string | null, mode: "replace" | "push" = "replace") {
  const url = new URL(window.location.href);
  if (value === null) url.searchParams.delete(name);
  else url.searchParams.set(name, value);
  window.history[mode === "push" ? "pushState" : "replaceState"](
    window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  window.dispatchEvent(new Event(WORKSPACE_URL_EVENT));
}
