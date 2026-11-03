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
}: {
  activity: WorkspaceState["latest_activity"];
  work?: WorkItem;
  pinned: boolean;
  busy: boolean;
  onPin: (entryId: string | null) => void;
}) {
  if (!activity)
    return (
      <div className="daily-thread">
        <div>
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
  return (
    <div className="daily-thread workspace-activity">
      <div>
        <span>
          {pinned ? "Pinned" : "Latest activity"}
          {activity.entry_kind
            ? ` · your ${activity.entry_kind.replaceAll("-", " ")}`
            : " · reading location"}
        </span>
        <p>
          {activity.body ||
            "A reading location is saved for this source version."}
        </p>
        <time className="workspace-note-context" dateTime={activity.updated_at}>
          Saved {displayDate(activity.updated_at)}
        </time>
      </div>
      <div>
        <span>Return to its source</span>
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
        <p className="workspace-note-context">
          {activity.version_id} · {activity.anchor}
        </p>
        {activity.entry_id && (
          <button
            className="daily-text-button"
            disabled={busy}
            onClick={() => onPin(pinned ? null : activity.entry_id)}
          >
            {pinned
              ? "Unpin saved item"
              : `Pin this ${activity.entry_kind?.replaceAll("-", " ") ?? "item"}`}
          </button>
        )}
      </div>
    </div>
  );
}
