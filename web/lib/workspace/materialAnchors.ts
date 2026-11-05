/** Retained page-local Unicode anchors; never infer another page or version. */
export function parseMaterialAnchor(value: string) {
  const match = /^material:([^:]+):page:(\d+):(\d+):(\d+)$/.exec(value);
  if (!match) return null;
  const page = Number(match[2]), start = Number(match[3]), end = Number(match[4]);
  return [page, start, end].every(Number.isSafeInteger) && page > 0 && start >= 0 && end > start
    ? { materialId: match[1]!, page, start, end } : null;
}
