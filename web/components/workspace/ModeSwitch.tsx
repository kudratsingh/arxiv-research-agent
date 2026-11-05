import Link from "next/link";
import { changeContextHref, useProductContext, type ProductMode } from "@/lib/workspace/productContext";
import { useWorkspaceHref } from "@/lib/workspace/urlState";

export function ModeSwitch({ path }: { path: string }) {
  const context = useProductContext();
  const current = useWorkspaceHref(path);
  return <div className="ws-mode-control">
    <nav aria-label="Workspace mode" className="ws-mode-switch">
      {([["learn", "Explore & Learn"], ["research", "Research"]] as const).map(([mode, label]) =>
        <Link key={mode} href={changeContextHref(current, { ...context, mode: mode as ProductMode, project: mode === "learn" ? null : context.project, thread: null })}
          prefetch={false} scroll={false} aria-current={context.mode === mode ? "true" : undefined}>{label}</Link>)}
    </nav>
    {context.invalid && <p className="daily-muted">Unknown mode or context. Invalid context is not selected; no saved record was changed.</p>}
  </div>;
}
