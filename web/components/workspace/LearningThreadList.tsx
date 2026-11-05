import Link from "next/link";
import { useContextIndex } from "@/lib/workspace/useContextIndex";
import { contextHref } from "@/lib/workspace/productContext";
export default function LearningThreadList({ owner }: { owner: string }) {
  const { index, error, reload } = useContextIndex();
  if (!index) return error ? <p role="alert">{error}<button type="button" onClick={() => void reload()}>Retry learning threads</button></p> : <p aria-busy="true">Loading your saved learning threads…</p>;
  if (index.principal_key_id !== owner) return <p role="alert">This learning index belongs to a different local account.</p>;
  return <><p>Manual learning goals stay available without a research project or organizing question.</p><ul>{index.threads.map(thread => <li key={thread.id}><Link href={contextHref(`/workspace/threads/${thread.id}`, { mode: "learn", project: null, thread: thread.id, explicit: true, invalid: false })} prefetch={false}>{thread.data.title}</Link> · {thread.data.status} · {thread.data.origin.project_id ? "project-linked" : "source-linked"}</li>)}</ul>{!index.threads.length && <p>No saved learning threads. Open an exact source in Reader and choose Learn this prerequisite.</p>}</>;
}
