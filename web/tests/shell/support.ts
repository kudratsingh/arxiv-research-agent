/**
 * WO-08's test harness: a `matchMedia` that answers width questions.
 *
 * jsdom performs no layout, so its `matchMedia` cannot resolve
 * `(min-width: 768px)` against anything. That is not a gap the shell can
 * paper over — the three modes in RC-04 *are* width questions — so the
 * tests supply the width instead, and the shell is exercised through the
 * exact API the browser gives it.
 *
 * `setViewportWidth` dispatches `change` on every live query, which is what
 * proves the shell re-reads the mode on a resize rather than only at mount.
 */

const MIN_WIDTH = /^\(min-width:\s*(\d+)px\)$/;
const PREFERS_DARK = "(prefers-color-scheme: dark)";

type Listener = (event: MediaQueryListEvent) => void;

interface FakeQuery {
  query: string;
  matches: boolean;
  listeners: Set<Listener>;
  list: MediaQueryList;
}

let original: typeof window.matchMedia | undefined;
let installed = false;
let width = 1440;
let prefersDark = false;
const queries = new Set<FakeQuery>();

function evaluate(query: string): boolean {
  if (query === PREFERS_DARK) return prefersDark;
  const match = MIN_WIDTH.exec(query.trim());
  if (!match?.[1]) return false;
  return width >= Number.parseInt(match[1], 10);
}

function makeQuery(query: string): MediaQueryList {
  const entry: FakeQuery = {
    query,
    matches: evaluate(query),
    listeners: new Set<Listener>(),
    // Replaced immediately below; the object needs to exist first so the
    // closures can refer to `entry`.
    list: null as unknown as MediaQueryList,
  };

  const list = {
    get matches() {
      return entry.matches;
    },
    media: query,
    onchange: null,
    addEventListener: (type: string, listener: Listener) => {
      if (type === "change") entry.listeners.add(listener);
    },
    removeEventListener: (type: string, listener: Listener) => {
      if (type === "change") entry.listeners.delete(listener);
    },
    addListener: (listener: Listener) => entry.listeners.add(listener),
    removeListener: (listener: Listener) => entry.listeners.delete(listener),
    dispatchEvent: () => true,
  } as unknown as MediaQueryList;

  entry.list = list;
  queries.add(entry);
  return list;
}

function refresh(): void {
  for (const entry of queries) {
    const next = evaluate(entry.query);
    if (next === entry.matches) continue;
    entry.matches = next;
    const event = { matches: next, media: entry.query } as MediaQueryListEvent;
    for (const listener of [...entry.listeners]) listener(event);
  }
}

/** Install the fake. `width` is the viewport width every query resolves against. */
export function installMatchMedia(options: { width?: number; prefersDark?: boolean } = {}): void {
  if (!installed) {
    original = window.matchMedia;
    installed = true;
  }
  width = options.width ?? 1440;
  prefersDark = options.prefersDark ?? false;
  queries.clear();
  window.matchMedia = ((query: string) => makeQuery(query)) as typeof window.matchMedia;
}

/** Resize, and fire `change` on every query whose answer moved. */
export function setViewportWidth(next: number): void {
  width = next;
  refresh();
}

/** Flip the OS colour-scheme preference, and fire `change`. */
export function setPrefersDark(next: boolean): void {
  prefersDark = next;
  refresh();
}

/** Put the real (or absent) implementation back. */
export function uninstallMatchMedia(): void {
  if (!installed) return;
  queries.clear();
  if (original) {
    window.matchMedia = original;
  } else {
    // `delete` on a jsdom window property that was never defined is a no-op
    // rather than an error, which is the behaviour we want either way.
    Reflect.deleteProperty(window, "matchMedia");
  }
  installed = false;
}

/** The three widths RC-04's modes are defined at, for `it.each`. */
export const MODE_WIDTHS = {
  drawer: 412,
  compact: 900,
  expanded: 1440,
} as const;
