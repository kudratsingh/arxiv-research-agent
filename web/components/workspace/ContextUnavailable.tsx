import Link from "next/link";
import { contextHref, type ProductContext } from "@/lib/workspace/productContext";
export function ContextUnavailable({ reason, context }: { reason: string; context: ProductContext }) {
  return <section className="daily-empty" data-workspace-unavailable=""><h1>{reason === "select_or_create_project" ? "Choose a research project." : "This context is unavailable."}</h1>
    <p>{reason === "project_archived" ? "Archived projects keep shared sources and notes." : reason === "select_or_create_project" ? "Choose a project question. Your saved organizing question was not imported." : "This project or thread is unavailable in your account. No substitute was selected."}</p>
    <Link className="daily-link" href={contextHref("/workspace/projects", { ...context, project: null, thread: null })} prefetch={false}>Create or select a project →</Link>
    <Link className="daily-link" href={contextHref("/workspace/library", context)} prefetch={false}>Open shared Library →</Link>
  </section>;
}
