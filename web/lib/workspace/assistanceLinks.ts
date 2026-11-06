import { readerHref, type ResumeContext } from "./api";

/** Saved output identity is a link to an owned job, never execution authority. */
export function assistanceResumeHref(entryId: string, source: { work_id: string; version_id: string }, origin: ResumeContext, returnTo = origin.return_to): string | null {
  const id = /^assistance-(fake-[a-f0-9]{40})$/.exec(entryId)?.[1];
  if (!id) return null;
  const href = readerHref(source, source.version_id, "understand", undefined, returnTo);
  const [path, fragment] = href.split("#");
  const [pathname, query] = path!.split("?");
  const params = new URLSearchParams(query);
  params.set("assistance", id); params.set("mode", origin.mode);
  if (origin.project_id) params.set("project", origin.project_id);
  if (origin.thread_id) params.set("thread", origin.thread_id);
  return `${pathname}?${params}${fragment ? `#${fragment}` : ""}`;
}
