import { readerHref, type Activity, type WorkItem } from "./api";
import { contextHref, type ProductContext } from "./productContext";

/** Activity's immutable version/revision wins over a later entry or current mode. */
export function activityDestination(activity: Activity, work: WorkItem | undefined, current: ProductContext) {
  const source = work?.versions.find(version => version.version_id === activity.version_id);
  const currentEntry = work?.entries.find(value => value.id === activity.entry_id);
  const entry = currentEntry?.revision === activity.revision ? currentEntry : undefined;
  const resume = activity.entry_id ? entry?.context : work?.reading.revision === activity.revision ? work.reading.context : null;
  const context = resume ? { mode: resume.mode, project: resume.project_id, thread: resume.thread_id, explicit: true, invalid: false } : current;
  return { sourceTitle: source?.title || (work?.version_id === activity.version_id ? work.title : "Earlier retained source version"),
    href: work ? contextHref(readerHref(work, activity.version_id, activity.anchor, currentEntry && !entry ? undefined : activity.entry_id ?? undefined, resume?.return_to ?? contextHref("/workspace/today", context)), context) : null };
}
