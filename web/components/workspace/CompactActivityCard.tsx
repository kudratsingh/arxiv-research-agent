import { loadContextReadouts } from "./contextModules";
import Link from "next/link";
import { lazy, Suspense, useState } from "react";
import { type ProductContext } from "@/lib/workspace/productContext";
import { activityDestination } from "@/lib/workspace/activity";
import type { WorkItem, WorkspaceState } from "@/lib/workspace/api";
const ActivityOptions = lazy(() => loadContextReadouts().then(module => ({ default: module.ActivityOptions })));

/** The continuation itself is eager; only its closed pin/options disclosure loads later. */
export function CompactActivityCard({ activity, work, pinned, busy, onPin, context }: { activity: NonNullable<WorkspaceState["latest_activity"]>; work?: WorkItem; context: ProductContext; pinned: boolean; busy: boolean; onPin: (id: string | null) => void }) {
  const [opened, setOpened] = useState(false);
  const target = activityDestination(activity, work, context);
  return <div className="daily-thread workspace-activity workspace-continuation"><div><h2>Continue reading</h2>
    <span>{pinned ? "Pinned" : "Latest activity"}{activity.entry_kind ? ` · your ${activity.entry_kind.replaceAll("-", " ")}` : " · reading location"}</span>{activity.body && <p className="workspace-activity-body">{activity.body}</p>}
  </div><div>{target.href ? <Link className="workspace-activity-link" href={target.href} prefetch={false}>{target.sourceTitle} →</Link> : <p>The source is unavailable in the loaded view. Its saved activity has not been moved to another source.</p>}
    <details className="workspace-continuation-options" onToggle={event => { if (event.currentTarget.open) setOpened(true); }}><summary>Source and pin options</summary>{opened && <Suspense fallback={<p aria-busy="true">Opening saved source options…</p>}><ActivityOptions activity={activity} pinned={pinned} busy={busy} onPin={onPin} /></Suspense>}</details>
  </div></div>;
}
