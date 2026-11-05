import { displayDate, type Activity } from "@/lib/workspace/api";
export function ActivityOptions({ activity, pinned, busy, onPin }: { activity: Activity; pinned: boolean; busy: boolean; onPin: (id: string | null) => void }) {
  return <><time className="workspace-note-context" dateTime={activity.updated_at}>Saved {displayDate(activity.updated_at)}</time>
    <p className="workspace-note-context">{activity.version_id} · {activity.anchor}</p>
    {activity.entry_id && <button className="daily-text-button" disabled={busy} onClick={() => onPin(pinned ? null : activity.entry_id)}>{pinned ? "Unpin saved item" : `Pin this ${activity.entry_kind?.replaceAll("-", " ") ?? "item"}`}</button>}
  </>;
}
