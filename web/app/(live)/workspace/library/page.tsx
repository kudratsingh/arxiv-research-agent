import { Suspense } from "react";
import { LiveLibrary } from "@/components/workspace/Library";
export default function Page() {
  return (
    <Suspense fallback={<p className="daily-muted">Opening your Library…</p>}>
      <LiveLibrary />
    </Suspense>
  );
}
