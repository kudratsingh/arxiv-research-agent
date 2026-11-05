/** Bounded, private, current-document recovery when browser storage fails. */
const records = new Map<string, unknown>();
export function recallDraft<T>(key: string): T | undefined { return records.get(key) as T | undefined; }
export function rememberDraft<T>(key: string, value: T) {
  if (!records.has(key) && records.size >= 40) throw new Error("Current-tab draft recovery is full");
  records.set(key, value);
}
export function forgetDraft(key: string) { records.delete(key); }
/** Tests model separate browser documents; unmount/remount within one test keeps recovery. */
export function resetDraftMemory() { records.clear(); }
