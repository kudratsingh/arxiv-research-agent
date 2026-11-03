import { requestWorkspaceJSON } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/generated/schema";

type Serialized<T> = T extends (infer Item)[]
  ? Serialized<Item>[]
  : T extends object
    ? { [Key in keyof T]-?: Serialized<T[Key]> }
    : T;
type Schemas = components["schemas"];
export type WorkspaceState = Serialized<Schemas["WorkspaceState"]>;
export type WorkItem = Serialized<Schemas["WorkItem"]>;
export type ProfileData = Serialized<Schemas["ProfileData"]>;
export type ReadingData = Serialized<Schemas["ReadingData"]>;
export type ReadingRevision = Serialized<Schemas["ReadingRevision"]>;
export type EntryRevision = Serialized<Schemas["EntryRevision"]>;
export type ImportPreview = Serialized<Schemas["ImportPreview"]>;
export type SourceStatus = Serialized<Schemas["SourceStatus"]>;
export type ScheduleData = Serialized<Schemas["ScheduleData"]>;
export type Activity = Serialized<Schemas["Activity"]>;
export type InterestCoverage = Serialized<Schemas["InterestCoverage"]>;
export type ReviewIndex = Serialized<Schemas["ReviewIndex"]>;
export type ReviewPacket = Serialized<Schemas["ReviewPacket"]>;
export type ReviewCandidate = Serialized<Schemas["ReviewCandidate"]>;
export type UsefulnessFeedback = Serialized<Schemas["UsefulnessFeedback"]>;
export type MaterialInfo = Serialized<Schemas["MaterialInfo"]>;
export type MaterialDocument = Serialized<Schemas["MaterialDocument"]>;
export type RetainedSpan = Serialized<Schemas["RetainedSpan"]>;
export type RetainedAvailability = Serialized<Schemas["RetainedAvailability"]>;
export type FakeRequestPreview = Serialized<Schemas["FakeRequestPreview"]>;
export type FakeJob = Serialized<Schemas["FakeJob"]>;
export type FakeDraft = Serialized<Schemas["FakeDraft"]>;
export type FakeResult = Serialized<Schemas["FakeResult"]>;
export type FakeUsage = Serialized<Schemas["FakeUsage"]>;

export class WorkspaceError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "WorkspaceError";
  }
}

/** Same-origin only; the existing Node proxy owns credential injection. */
export async function workspaceRequest<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  try {
    return await requestWorkspaceJSON<T>(path, body, signal);
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 0;
    throw new WorkspaceError(
      status,
      status === 409
        ? "This record changed in another tab. Your text is still here. Reload the saved version before deciding how to reconcile it."
        : status === 401 || status === 403
          ? "The local account cannot make this request. Check the workspace service configuration. Your text is still here."
          : status > 0
            ? "The workspace could not complete this request. Your text is still here; retry when the service is available."
            : "The local workspace is unavailable. Your text is still here. Start or reconnect the service, then retry.",
    );
  }
}

export function requestId() {
  return crypto.randomUUID();
}

export function displayDate(value: string | null | undefined) {
  if (!value) return "Date unknown";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unknown"
    : date.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

export function readerHref(
  item: Pick<WorkItem, "work_id">,
  version?: string,
  anchor?: string,
  entryId?: string,
  returnTo?: string,
) {
  const params = new URLSearchParams();
  if (version) params.set("version", version);
  if (entryId) params.set("entry", entryId);
  if (returnTo) params.set("return_to", normalizeReaderReturnTo(returnTo));
  const query = params.size ? `?${params}` : "";
  return `/workspace/items/${encodeURIComponent(item.work_id)}${query}${anchor ? `#${encodeURIComponent(anchor)}` : ""}`;
}

/** Exact-version acquired text is independent of the immutable source record. */
export function readingMaterial(item: WorkItem, versionId?: string) {
  const version = item.versions.find(
    (value) => value.version_id === (versionId ?? item.version_id),
  ) ?? item;
  const retained = version.retained_materials ?? [];
  const pdf = retained.find((value) => value.format === "pdf");
  return { version, pdf, scope: version.available_scopes?.[0] ?? version.access_state };
}

/** A return link can only navigate within the three source-list routes. */
export function normalizeReaderReturnTo(value: string | null): string {
  if (!value || !value.startsWith("/workspace/") || /[\\\u0000-\u001f]/.test(value))
    return "/workspace/today";
  try {
    const target = value.split("#", 1)[0] ?? "";
    const separator = target.indexOf("?");
    const pathname = separator < 0 ? target : target.slice(0, separator);
    const search = new URLSearchParams(separator < 0 ? "" : target.slice(separator + 1));
    if (!["/workspace/today", "/workspace/library", "/workspace/radar", "/workspace/review"].includes(pathname))
      return "/workspace/today";
    const params = new URLSearchParams();
    if (pathname === "/workspace/review") {
      const packet = search.get("packet");
      if (packet && /^review-[a-f0-9]{32}$/.test(packet)) params.set("packet", packet);
    } else if (pathname === "/workspace/library") {
      const view = search.get("view");
      if (view && ["saved", "notes", "read", "archived", "all"].includes(view)) params.set("view", view);
    } else if (pathname === "/workspace/radar") {
      for (const key of ["q", "source_id", "access_state", "status", "days"]) {
        const item = search.get(key);
        if (item && item.length <= 500) params.set(key, item);
      }
    }
    return `${pathname}${params.size ? `?${params}` : ""}`;
  } catch {
    return "/workspace/today";
  }
}

export function errorMessage(error: unknown) {
  return error instanceof WorkspaceError
    ? error.message
    : "The request could not be completed. Your text is still here.";
}
