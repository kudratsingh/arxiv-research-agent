// `/learn` — the path library index (00 §5.5's second allowed surface).
//
// The route file is a mount point and nothing else: `PathListSurface` owns
// the fetch and all three of its states, and the shell plus the query client
// come from `app/(learn)/layout.tsx`. Keeping the page a server component
// costs the route nothing in first-load JavaScript.

import { PathListSurface } from "@/components/features/PathListSurface";

/** The `/learn` route entry. */
export default function LearnPage() {
  return <PathListSurface />;
}
