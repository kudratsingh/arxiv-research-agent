/** Stable FNV-1a over UTF-8 bytes, returned as an unsigned 32-bit number. */
export function coverSeed(workId: string): number {
  let hash = 2166136261;
  for (const byte of new TextEncoder().encode(workId)) {
    hash = Math.imul(hash ^ byte, 16777619);
  }
  return hash >>> 0;
}

const STOP_WORDS = new Set(["a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"]);

export function coverMonogram(title: string): string {
  const words = title.match(/[\p{L}\p{N}]+/gu) ?? [];
  const significant = words.filter((word) => !STOP_WORDS.has(word.toLocaleLowerCase("en")));
  const chosen = significant.length ? significant : words;
  return chosen.slice(0, 2).map((word) => Array.from(word)[0]).join("").toLocaleUpperCase("en");
}

export function coverSource(sourceId = ""): string {
  const category = sourceId.match(/(?:^|[^\p{L}\p{N}])(cs|math|stat|physics)[.-]([\p{L}\p{N}]+)/iu);
  if (category?.[1] && category[2]) return `${category[1].toLowerCase()}.${category[2].toUpperCase()}`;
  return sourceId.toLowerCase().includes("arxiv") ? "ARXIV" : "BLOG";
}
