import { requestWorkspaceJSON } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/generated/schema";

type Serialized<T> = T extends (infer Item)[]
  ? Serialized<Item>[]
  : T extends object
    ? { [Key in keyof T]-?: Serialized<T[Key]> }
    : T;
type Schemas = components["schemas"];
export type WorkspaceState = Omit<Serialized<Schemas["WorkspaceState"]>, "works"> & {
  works: WorkItem[];
  context?: ResolvedContext;
  active_edition?: ContextEdition | null;
};
export type WorkItem = Omit<Serialized<Schemas["WorkItem"]>, "entries" | "reading"> & {
  entries: EntryRevision[];
  reading: ReadingRevision;
  mode_relevance?: Record<string, unknown>;
};
export type ProfileData = Serialized<Schemas["ProfileData"]>;
export type ReadingData = Serialized<Schemas["ReadingData"]>;
export type ReadingRevision = Serialized<Schemas["ReadingRevision"]> & { context?: ResumeContext | null };
export type EntryRevision = Serialized<Schemas["EntryRevision"]> & { context?: ResumeContext | null };
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
export type ProductMode = Schemas["ResumeContext"]["mode"] & string;
export type ResumeContext = Serialized<Schemas["ResumeContext"]>;
export type ResolvedContext = Serialized<Schemas["ResolvedContext"]>;
export type ContextPreferences = Serialized<Schemas["ContextPreferences"]>;
export type ContextIndex = Serialized<Schemas["ContextIndex"]>;
export type ResearchProject = Serialized<Schemas["ResearchProject"]>;
export type ProjectDetail = Serialized<Schemas["ProjectDetail"]>;
export type ProjectSource = Serialized<Schemas["ProjectSource"]>;
export type LearningThread = Serialized<Schemas["LearningThread"]>;
export type ContextEdition = Serialized<Schemas["ContextEdition"]>;
export type ContextWorkspaceState = Serialized<Schemas["ContextWorkspaceState"]>;
export type ContextWorkPage = Serialized<Schemas["ContextWorkPage"]>;
export type SourceReference = Schemas["SourceReference"];
export type EntryReference = Schemas["EntryReference"];
export type ArtifactData = Schemas["ArtifactData"];
export type ProjectArtifact = Serialized<Schemas["ProjectArtifact"]>;
export type BoundSource = Serialized<Schemas["BoundSource"]>;
export type ProjectWrite = Schemas["ProjectWrite"];
export type ProjectSourceWrite = Schemas["ProjectSourceWrite"];
export type ProjectEntryWrite = Schemas["ProjectEntryWrite"];
export type ProjectArtifactWrite = Schemas["ProjectArtifactWrite"];
export type LearningThreadWrite = Schemas["LearningThreadWrite"];
export type ContextPreferencesWrite = Schemas["ContextPreferencesWrite"];
export type ContextEntryWrite = Schemas["ContextEntryWrite"];
export type ContextReadingWrite = Schemas["ContextReadingWrite"];

/** Same owned proxy boundary; this helper cannot start generation. */
export function contextRequest<T>(path = "", body?: unknown, signal?: AbortSignal): Promise<T> {
  return workspaceRequest<T>(`context${path}`, body, signal);
}

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

/** Constrained owned workspace context; never an external redirect. */
export function normalizeReaderReturnTo(value: string | null): string {
  if (!value || !value.startsWith("/workspace/") || /[\\\u0000-\u001f]/.test(value))
    return "/workspace/today";
  try {
    const [target = "", fragment = ""] = value.split("#", 2);
    const separator = target.indexOf("?");
    const pathname = separator < 0 ? target : target.slice(0, separator);
    const search = new URLSearchParams(separator < 0 ? "" : target.slice(separator + 1));
    const route = /^\/workspace\/(today|library|radar|review|projects|threads\/thread-[a-f0-9]{32})$/.exec(pathname)?.[1];
    if (!route) return "/workspace/today";
    const params = new URLSearchParams();
    const fields: Record<string, string[]> = {
      today: ["focus"], library: ["view", "focus"], review: ["packet"],
      radar: ["q", "source_id", "access_state", "status", "days", "cursor", "as_of", "focus"],
    };
    const patterns: Record<string, RegExp> = {
      mode: /^(learn|research)$/, project: /^project-[a-f0-9]{32}$/,
      thread: /^thread-[a-f0-9]{32}$/, packet: /^review-[a-f0-9]{32}$/,
      view: /^(saved|notes|read|archived|all)$/,
    };
    for (const key of ["mode", "project", "thread", ...(fields[route] ?? ["focus", "version", "entry"])]) {
      const item = search.get(key);
      const limit = key === "cursor" ? 2048 : key === "as_of" ? 80 : 500;
      if (item && item.length <= limit && !/[\\\u0000-\u001f\u007f]/.test(item) && (!patterns[key] || patterns[key].test(item))) params.set(key, item);
    }
    const anchor = fragment && fragment.length <= 500 && !/[\\\u0000-\u001f\u007f]/.test(fragment) ? `#${fragment}` : "";
    return `${pathname}${params.size ? `?${params}` : ""}${anchor}`;
  } catch {
    return "/workspace/today";
  }
}

export function errorMessage(error: unknown) {
  return error instanceof WorkspaceError
    ? error.message
    : "The request could not be completed. Your text is still here.";
}
