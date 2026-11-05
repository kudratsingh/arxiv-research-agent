import { useEffect } from "react";
import { workspaceRequest, type ReviewIndex, type WorkItem } from "@/lib/workspace/api";

/** Only Review-origin readers need this read-only neighbour lookup. */
export default function ReaderReviewContext({ returnTo, onReady }: {
  returnTo: string;
  onReady: (value: { returnTo: string; works: WorkItem[] }) => void;
}) {
  useEffect(() => {
    const controller = new AbortController();
    const packet = new URLSearchParams(returnTo.split("?")[1]).get("packet");
    workspaceRequest<ReviewIndex>(`review${packet ? `?packet_id=${encodeURIComponent(packet)}` : ""}`, undefined, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) onReady({ returnTo, works: value.packet && (!packet || value.packet.id === packet) ? value.packet.items.map((candidate) => candidate.work) : [] });
      }).catch(() => { /* An unavailable packet provides no invented neighbours. */ });
    return () => controller.abort();
  }, [returnTo, onReady]);
  return null;
}
