import Link from "next/link";
import { useRouter } from "next/navigation";
import { useContextIndex } from "@/lib/workspace/useContextIndex";
import { changeContextHref, commitContextNavigation, contextHref, useProductContext } from "@/lib/workspace/productContext";

export default function ProjectSelector() {
  const { index, error, reload } = useContextIndex();
  const context = useProductContext(), router = useRouter();
  const project = index?.projects.find(item => item.id === context.project);
  return <div className="workspace-controls ws-project-selector" aria-busy={!index && !error}>
    <label><span>Active research project</span>
      <select value={context.project ?? ""} disabled={!index} onChange={event => {
        const href = changeContextHref(`${location.pathname}${location.search}${location.hash}`, { ...context, mode: "research", project: event.target.value || null, thread: null });
        commitContextNavigation(href, target => router.push(target, { scroll: false }));
      }}>
        <option value="">{index ? "Choose a project" : "Loading projects…"}</option>
        {context.project && !project && <option value={context.project}>Unavailable project</option>}
        {index?.projects.map(item => <option key={item.id} value={item.id}>{item.data.title}{item.data.status === "archived" ? " (archived)" : ""}</option>)}
      </select>
    </label>
    {error && <p role="alert">{error} <button type="button" onClick={() => void reload()}>Retry projects</button></p>}
    <Link href={contextHref("/workspace/projects", { ...context, mode: "research", explicit: true })} prefetch={false} scroll={false} aria-label={project ? "Open project workspace" : "Create or select a project"} title={project ? "Open project question and details" : "Create or select a project"}><span className="ws-project-selector-link">{project ? "Project workspace " : "Create/select "}</span>↗</Link>
  </div>;
}
