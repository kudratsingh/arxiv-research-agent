"use client";

import { useSyncExternalStore } from "react";

export const SIDEBAR_STORAGE_KEY = "arxiv-agent.workspace-sidebar";
const PREFERENCE_EVENT = "workspace:sidebar";
const MOBILE_QUERY = "(max-width: 767px)";
const TABLET_QUERY = "(max-width: 1023px)";
let temporaryCollapsed = false;
let storageWriteFailed = false;

function subscribePreference(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(PREFERENCE_EVENT, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(PREFERENCE_EVENT, listener);
  };
}
export function serverSidebarCollapsed() { return false; }
export function readSidebarCollapsed() {
  if (storageWriteFailed) return temporaryCollapsed;
  try { return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true"; }
  catch { return temporaryCollapsed; }
}
export function setSidebarCollapsed(value: boolean) {
  temporaryCollapsed = value;
  try {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(value));
    storageWriteFailed = false;
  } catch { storageWriteFailed = true; }
  window.dispatchEvent(new Event(PREFERENCE_EVENT));
}
export function useSidebarPreference() {
  return useSyncExternalStore(subscribePreference, readSidebarCollapsed, serverSidebarCollapsed);
}

export type SidebarViewport = "mobile" | "tablet" | "desktop";
export function serverSidebarViewport(): SidebarViewport { return "desktop"; }
function readViewport(): SidebarViewport {
  if (!window.matchMedia) return "desktop";
  if (window.matchMedia(MOBILE_QUERY).matches) return "mobile";
  return window.matchMedia(TABLET_QUERY).matches ? "tablet" : "desktop";
}
function subscribeViewport(listener: () => void) {
  if (!window.matchMedia) return () => {};
  const queries = [window.matchMedia(MOBILE_QUERY), window.matchMedia(TABLET_QUERY)];
  for (const query of queries) query.addEventListener("change", listener);
  return () => { for (const query of queries) query.removeEventListener("change", listener); };
}
export function useSidebarViewport() {
  return useSyncExternalStore(subscribeViewport, readViewport, serverSidebarViewport);
}
