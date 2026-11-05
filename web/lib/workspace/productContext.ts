import { useMemo, useSyncExternalStore } from "react";
import { useWorkspaceSearch } from "./urlState";
import { allowWorkspaceNavigation } from "./navigationGuard";
import { requestWorkspaceNavigation } from "./navigation";
import { normalizeReaderReturnTo, type ResumeContext } from "./api";

export type ProductMode = "learn" | "research";
export interface ProductContext {
  mode: ProductMode;
  project: string | null;
  thread: string | null;
  explicit: boolean;
  invalid: boolean;
}
let resolved: { key: string; mode: ProductMode } | null = null;
const listeners = new Set<() => void>();
function subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }
function contextIdentity(href: string) {
  const url = new URL(href, "file:///"), query = new URLSearchParams();
  for (const field of ["mode", "project", "thread"]) { const value = url.searchParams.get(field); if (value !== null) query.set(field, value); }
  return `${url.pathname}?${query}`;
}
function currentKey() { return contextIdentity(`${location.pathname}${location.search}`); }
export function publishResolvedMode(mode: ProductMode, key: string) {
  key = contextIdentity(key);
  if (currentKey() !== key || resolved?.key === key && resolved.mode === mode) return;
  resolved = { key, mode }; listeners.forEach(listener => listener());
}
export function validContextId(value: string | null, kind: "project" | "thread"): string | null {
  return value && new RegExp(`^${kind}-[a-f0-9]{32}$`).test(value) ? value : null;
}
export function parseProductContext(params: URLSearchParams, fallback: ProductMode = "learn"): ProductContext {
  const raw = params.get("mode"), projectId = params.get("project"), threadId = params.get("thread");
  const project = validContextId(projectId, "project"), thread = validContextId(threadId, "thread");
  const mode = raw === null ? fallback : raw === "research" ? "research" : "learn";
  return { mode, project, thread, explicit: raw !== null || projectId !== null || threadId !== null,
    invalid: raw !== null && raw !== "learn" && raw !== "research" || projectId !== null && !project || threadId !== null && !thread };
}
export function useProductContext(fallback?: ProductMode): ProductContext {
  const saved = useSyncExternalStore(subscribe, () => resolved?.key === currentKey() ? resolved.mode : "learn", () => "learn" as ProductMode);
  const search = useWorkspaceSearch();
  return useMemo(() => parseProductContext(new URLSearchParams(search), fallback ?? saved), [search, fallback, saved]);
}
/** Carries only typed identity; authored questions and notes never enter URLs. */
export function contextHref(href: string, context: ProductContext): string {
  const url = new URL(href, "file:///");
  if (!href.startsWith("/workspace/") || !url.pathname.startsWith("/workspace/")) return href;
  if (context.explicit || context.mode === "research") url.searchParams.set("mode", context.mode);
  if (context.project) url.searchParams.set("project", context.project);
  if (context.thread) url.searchParams.set("thread", context.thread);
  return `${url.pathname}${url.search}${url.hash}`;
}
export function changeContextHref(href: string, context: ProductContext): string {
  const url = new URL(href, "file:///");
  for (const key of ["mode", "project", "thread", "cursor", "as_of"]) url.searchParams.delete(key);
  return contextHref(`${url.pathname}${url.search}${url.hash}`, { ...context, explicit: true });
}
/** Veto first. Native history and scroll intent change together only on success. */
export function commitContextNavigation(href: string, commit: (href: string) => void): boolean {
  if (!allowWorkspaceNavigation(href)) return false;
  requestWorkspaceNavigation(href);
  commit(href);
  return true;
}
export function contextQuery(context: ProductContext): URLSearchParams {
  const params = new URLSearchParams({ mode: context.mode });
  if (context.project) params.set("project", context.project);
  if (context.thread) params.set("thread", context.thread);
  return params;
}
export function resumeContext(context: ProductContext, returnTo: string): ResumeContext {
  return { mode: context.mode, project_id: context.project, thread_id: context.thread,
    return_to: normalizeReaderReturnTo(contextHref(returnTo, context)) };
}
