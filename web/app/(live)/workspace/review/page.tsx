import { Suspense } from "react";
import { CandidateReview } from "@/components/workspace/CandidateReview";

export default function Page() {
  return (
    <Suspense
      fallback={<p className="daily-muted">Opening candidate review…</p>}
    >
      <CandidateReview />
    </Suspense>
  );
}
