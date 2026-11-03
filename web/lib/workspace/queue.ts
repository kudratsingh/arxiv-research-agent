import { readingMaterial, type WorkItem, type WorkspaceState } from "./api";

/** Edition order with exact retained versions, before reading-status filtering. */
export function todayEditionQueue(state: WorkspaceState): WorkItem[] {
  const edition = state.editions[0];
  if (!edition) return [];
  return edition.work_ids.flatMap((id) => {
    const work = state.works.find((item) => item.work_id === id);
    if (!work) return [];
    const version = edition.work_versions[id];
    if (!version) return [work];
    const retained = work.versions.find((item) => item.version_id === version);
    if (!retained) return [];
    return [{
      ...work,
      version_id: version,
      version_label: retained.version_label,
      title: retained.title || work.title,
      url: retained.url || work.url,
      authors: retained.authors.length ? retained.authors : work.authors,
      abstract: retained.abstract,
      access_state: retained.access_state,
      content_hash: retained.content_hash,
    }];
  });
}

/** The visible edition; callers may supply a clock for deterministic snapshots. */
export function todayQueue(state: WorkspaceState, now = new Date()): WorkItem[] {
  return todayEditionQueue(state).filter((item) =>
    !["dismissed", "archived"].includes(item.reading.status) &&
    (item.reading.status !== "snoozed" || !item.reading.snoozed_until ||
      new Date(item.reading.snoozed_until) <= now));
}

export function libraryQueue(state: WorkspaceState, view: string): WorkItem[] {
  const filter = ["saved", "notes", "read", "archived", "all"].includes(view) ? view : "saved";
  return state.works.filter((item) => filter === "all"
    ? item.entries.length > 0 || item.reading.status !== "unread"
    : filter === "notes" ? item.entries.length > 0 : item.reading.status === filter);
}

/** Keep the requested id in the URL after a write so Undo restores its focus. */
export function resolveFocus(
  visible: readonly WorkItem[], editionOrder: readonly string[], focusId: string | null,
): WorkItem | null {
  const selected = visible.find((item) => item.work_id === focusId);
  if (selected) return selected;
  const removedIndex = focusId === null ? -1 : editionOrder.indexOf(focusId);
  if (removedIndex >= 0) {
    const byId = new Map(visible.map((item) => [item.work_id, item]));
    for (const id of editionOrder.slice(removedIndex + 1)) {
      const next = byId.get(id);
      if (next) return next;
    }
    for (const id of editionOrder.slice(0, removedIndex).reverse()) {
      const previous = byId.get(id);
      if (previous) return previous;
    }
  }
  return visible[0] ?? null;
}

/** No wrapping. Unknown focus has index -1 and no navigable neighbours. */
export function neighbours(queue: readonly WorkItem[], focusId: string | null) {
  const index = queue.findIndex((item) => item.work_id === focusId);
  return {
    previous: index > 0 ? queue[index - 1]! : null,
    next: index >= 0 && index < queue.length - 1 ? queue[index + 1]! : null,
    index,
    count: queue.length,
  };
}

/** WorkCard precedence: explicit edition version, saved version, latest version. */
export function readerTarget(item: WorkItem, explicitVersion?: string) {
  const version = explicitVersion || item.reading.version_id || item.version_id;
  const material = readingMaterial(item, version);
  const anchor = item.reading.revision > 0 && item.reading.version_id === version
    ? item.reading.anchor
    : material.pdf?.first_anchor ?? `${material.version.access_state}:0`;
  return { version, anchor };
}
