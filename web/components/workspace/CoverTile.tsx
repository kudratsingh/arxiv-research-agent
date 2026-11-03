import { coverMonogram, coverSeed, coverSource } from "@/lib/workspace/cover";

export function CoverTile({ work_id, title, source_id, size = "hero" }: {
  work_id: string;
  title: string;
  source_id?: string;
  size?: "hero" | "bar" | "queue";
}) {
  const hash = coverSeed(work_id);
  return (
    <div className="ws-cover" data-size={size} data-pattern={hash % 6} data-turn={(hash >>> 3) % 4} data-invert={(hash >>> 5) % 2} aria-hidden="true">
      <span className="ws-cover-pattern" />
      <span className="ws-cover-source">{coverSource(source_id)}</span>
      <span className="ws-cover-monogram">{coverMonogram(title)}</span>
    </div>
  );
}
