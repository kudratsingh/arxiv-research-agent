// `/learn/sessions/[id]` — one guided reading session.
//
// The segment is awaited here so `SessionDetailSurface` receives a plain id;
// the surface owns the fetch, the turn submission and every failure state.

import { SessionDetailSurface } from "@/components/features/SessionDetailSurface";

/**
 * The `/learn/sessions/[id]` route entry.
 *
 * `async` because App Router `params` is a promise.
 */
export default async function LearnSessionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <SessionDetailSurface sessionId={id} />;
}
