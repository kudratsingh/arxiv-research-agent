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
) {
  const query = version ? `?version=${encodeURIComponent(version)}` : "";
  return `/workspace/items/${encodeURIComponent(item.work_id)}${query}${anchor ? `#${encodeURIComponent(anchor)}` : ""}`;
}

export function errorMessage(error: unknown) {
  return error instanceof WorkspaceError
    ? error.message
    : "The request could not be completed. Your text is still here.";
}
