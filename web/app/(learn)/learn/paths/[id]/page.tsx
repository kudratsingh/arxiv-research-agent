// `/learn/paths/[id]` — one reading path (00 §5.5's third allowed surface).
//
// The segment is awaited here so `PathDetailSurface` receives a plain id and
// stays free of route concerns; the surface owns the fetch, its loading frame
// and its unavailable state.

import { PathDetailSurface } from "@/components/features/PathDetailSurface";

/**
 * The `/learn/paths/[id]` route entry.
 *
 * `async` because App Router `params` is a promise; the id is passed on raw
 * and encoded again at every link that rebuilds this URL.
 */
export default async function LearnPathPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <PathDetailSurface pathId={id} />;
}
