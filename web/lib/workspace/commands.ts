/** Data commands belong only to the current actionable control, never its copy. */
export const PAGE_COMMANDS = [
  "next", "prev", "open", "save", "dismiss", "snooze", "undo", "mark-read",
  "check-sources", "time-5", "time-15", "time-45", "next-page",
  "label-useful", "label-maybe", "label-irrelevant",
] as const;

export const ROUTE_COMMANDS = {
  "go-today": "/workspace/today",
  "go-radar": "/workspace/radar",
  "go-library": "/workspace/library",
  "go-interests": "/workspace/interests",
  "go-sources": "/workspace/operations",
  "go-review": "/workspace/review",
} as const;

export const GLOBAL_COMMANDS = [
  "focus-composer", "command-palette", "shortcuts", "toggle-sidebar", "escape",
  "theme-light", "theme-dark", "theme-system", "export", "go-preview", "go-research",
] as const;
export type WorkspaceCommand = typeof PAGE_COMMANDS[number] | keyof typeof ROUTE_COMMANDS | typeof GLOBAL_COMMANDS[number];
export type KeySequence = { key: "g"; at: number };
export const KEY_SEQUENCE_TIMEOUT = 1000;

const KEYS: Readonly<Record<string, WorkspaceCommand>> = {
  j: "next", k: "prev", o: "open", s: "save", d: "dismiss", z: "snooze", u: "undo",
  ArrowRight: "next", ArrowLeft: "prev", Enter: "open",
  "/": "focus-composer", "?": "shortcuts", "[": "toggle-sidebar",
  "1": "label-useful", "2": "label-maybe", "3": "label-irrelevant",
};
const ROUTE_KEYS: Readonly<Record<string, WorkspaceCommand>> = {
  t: "go-today", r: "go-radar", l: "go-library", i: "go-interests", s: "go-sources", v: "go-review",
};

type CommandKeyEvent = Pick<KeyboardEvent,
  "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey" | "defaultPrevented" |
  "isComposing" | "target" | "timeStamp">;
export interface KeyCommandResult { command: WorkspaceCommand | null; sequence: KeySequence | null }

/** Pure interpretation: Shell owns the sequence ref, preventDefault and execution.
 * Every open modal owns its keys. Palette input navigation is handled locally;
 * Escape remains available for dialog/drawer dismissal.
 */
export function commandForKey(event: CommandKeyEvent, sequence: KeySequence | null = null): KeyCommandResult {
  const none: KeyCommandResult = { command: null, sequence: null };
  if (event.defaultPrevented || event.isComposing) return none;
  const target = event.target instanceof Element ? event.target : null;
  if (event.key === "Escape") return { ...none, command: "escape" };
  const modal = 'dialog[open], [role="dialog"][aria-modal="true"]';
  if (target?.closest(modal) || document.querySelector(modal)) return none;
  if ((event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === "k") {
    return { ...none, command: "command-palette" };
  }
  if (event.metaKey || event.ctrlKey || event.altKey) return none;
  if (event.shiftKey && event.key !== "?") return none;
  if (target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) return none;
  if (["Enter", "ArrowLeft", "ArrowRight"].includes(event.key) &&
    !target?.matches("body, main#main, .ws-bar")) return none;
  if (sequence && event.timeStamp - sequence.at >= 0 && event.timeStamp - sequence.at <= KEY_SEQUENCE_TIMEOUT) {
    const command = ROUTE_KEYS[event.key];
    if (command) return { ...none, command };
  }
  if (event.key === "g") return { command: null, sequence: { key: "g", at: event.timeStamp } };
  return { ...none, command: KEYS[event.key] ?? null };
}


/** One slash resolver for both the displayed choices and the submitted action. */
export function commandsForPrefix(line: string): WorkspaceCommand[] {
  const [name, argument, ...extra] = line.trim().toLowerCase().split(/\s+/);
  if (!name || extra.length) return [];
  if (name === "theme") return argument === "light" || argument === "dark" || argument === "system" ? [`theme-${argument}`] : [];
  if (name === "time") return argument === "5" || argument === "15" || argument === "45" ? [`time-${argument}`] : [];
  if (argument !== undefined) return [];
  const aliases: Readonly<Record<string, WorkspaceCommand>> = {
    today: "go-today", radar: "go-radar", library: "go-library", interests: "go-interests", sources: "go-sources", review: "go-review", preview: "go-preview", research: "go-research",
  };
  if (Object.hasOwn(aliases, name)) return [aliases[name]!];
  return [...PAGE_COMMANDS, ...Object.keys(ROUTE_COMMANDS) as (keyof typeof ROUTE_COMMANDS)[], ...GLOBAL_COMMANDS]
    .filter(command => command.startsWith(name));
}
