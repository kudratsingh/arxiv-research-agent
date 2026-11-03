"use client";

import Link from "next/link";
import {
  displayDate,
  readerHref,
  type WorkItem,
  type WorkspaceState,
} from "@/lib/workspace/api";

/** The server chooses the activity using its durable mutation sequence. */
export function ActivityCard({
  activity,
  work,
  pinned,
  busy,
  onPin,
  compact = false,
}: {
  activity: WorkspaceState["latest_activity"];
  work?: WorkItem;
  pinned: boolean;
  busy: boolean;
  onPin: (entryId: string | null) => void;
  compact?: boolean;
}) {
  if (!activity)
    return (
      <div className={compact ? "daily-thread workspace-activity workspace-continuation" : "daily-thread"}>
        <div>
          {compact && <h2>Continue your question</h2>}
          <span>No saved activity yet</span>
          <p>
            Open a source and save a question, or keep a reading location to
            return to.
          </p>
        </div>
      </div>
    );
  const source = work?.versions.find(
    (version) => version.version_id === activity.version_id,
  );
  const sourceTitle =
    source?.title ||
    (work?.version_id === activity.version_id
      ? work.title
      : "Earlier retained source version");
  const options = <>
    <time className="workspace-note-context" dateTime={activity.updated_at}>
      Saved {displayDate(activity.updated_at)}
    </time>
    <p className="workspace-note-context">{activity.version_id} · {activity.anchor}</p>
    {activity.entry_id && <button className="daily-text-button" disabled={busy}
      onClick={() => onPin(pinned ? null : activity.entry_id)}>
      {pinned ? "Unpin saved item" : `Pin this ${activity.entry_kind?.replaceAll("-", " ") ?? "item"}`}
    </button>}
  </>;
  return (
    <div className={`daily-thread workspace-activity${compact ? " workspace-continuation" : ""}`}>
      <div>
        {compact && <h2>Continue your question</h2>}
        <span>
          {pinned ? "Pinned" : "Latest activity"}
          {activity.entry_kind
            ? ` · your ${activity.entry_kind.replaceAll("-", " ")}`
            : " · reading location"}
        </span>
        {(!compact || activity.body) && <p className="workspace-activity-body">
          {activity.body ||
            "A reading location is saved for this source version."}
        </p>}
      </div>
      <div>
        {!compact && <span>Return to its source</span>}
        {work ? (
          <Link
            className="workspace-activity-link"
            href={readerHref(
              work,
              activity.version_id,
              activity.anchor,
              activity.entry_id ?? undefined,
              "/workspace/today",
            )}
            prefetch={false}
          >
            {sourceTitle} →
          </Link>
        ) : (
          <p>
            The source is unavailable in the loaded view. Its saved activity has
            not been moved to another source.
          </p>
        )}
        {compact ? <details className="workspace-continuation-options"><summary>Source and pin options</summary>{options}</details> : options}
      </div>
    </div>
  );
}
