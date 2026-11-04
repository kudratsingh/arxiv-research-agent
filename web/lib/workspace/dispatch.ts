import { GLOBAL_COMMANDS, PAGE_COMMANDS, ROUTE_COMMANDS, type WorkspaceCommand } from "./commands";

const registry: readonly WorkspaceCommand[] = [
  ...PAGE_COMMANDS,
  ...Object.keys(ROUTE_COMMANDS) as (keyof typeof ROUTE_COMMANDS)[],
  ...GLOBAL_COMMANDS,
];

function usable(element: HTMLElement): boolean {
  return element.isConnected && !element.matches(":disabled, [aria-disabled='true']") &&
    !element.closest("[inert], [hidden], [aria-hidden='true']");
}

/** Resolve the current element on every invocation; never retain route controls. */
function control(scope: HTMLElement, selector: string): HTMLElement | undefined {
  return Array.from(scope.querySelectorAll<HTMLElement>(selector)).find(usable);
}

export function dispatchWorkspaceCommand(command: WorkspaceCommand): boolean {
  const scope = document.querySelector<HTMLElement>(".workspace-app");
  if (!scope) return false;
  if (command === "command-palette" || command === "shortcuts") return false;
  if (command in ROUTE_COMMANDS) {
    location.assign(ROUTE_COMMANDS[command as keyof typeof ROUTE_COMMANDS]);
    return true;
  }
  if (command === "focus-composer") {
    const input = control(scope, ".ws-composer-input");
    if (!input) return false;
    input.focus();
    return true;
  }
  if (command === "escape") {
    const close = control(scope, '[data-command="escape"]');
    if (close) { close.click(); return true; }
    const active = document.activeElement;
    if (active instanceof HTMLElement && scope.contains(active) &&
      active.matches('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) {
      active.blur();
      return true;
    }
    return false;
  }
  let selector = `[data-command="${command}"]`;
  if (command.startsWith("theme-")) {
    const theme = command.slice("theme-".length);
    selector = `input[type="radio"][name="theme-preference"][value="${theme}"]`;
  } else if (command === "export") {
    selector = 'a[href="/api/workspace/export"]';
  }
  const target = control(scope, selector);
  if (!target) return false;
  target.click();
  return true;
}

/** Interpret human-readable aliases, then resolve against the current controls. */
export function dispatchWorkspacePrefix(line: string): boolean {
  const words = line.trim().toLowerCase().split(/\s+/);
  const name = words[0];
  if (!name || words.length > 2) return false;
  const argument = words[1];
  if (name === "theme") {
    if (argument !== "light" && argument !== "dark" && argument !== "system") return false;
    return dispatchWorkspaceCommand(`theme-${argument}`);
  }
  if (name === "time") {
    if (argument !== "5" && argument !== "15" && argument !== "45") return false;
    return dispatchWorkspaceCommand(`time-${argument}`);
  }
  if (argument !== undefined) return false;
  const routes: Readonly<Record<string, keyof typeof ROUTE_COMMANDS>> = {
    today: "go-today", radar: "go-radar", library: "go-library",
    interests: "go-interests", sources: "go-sources", review: "go-review",
  };
  const route = Object.hasOwn(routes, name) ? routes[name] : undefined;
  if (route) return dispatchWorkspaceCommand(route);
  return registry.some((command) => command.startsWith(name) && dispatchWorkspaceCommand(command));
}
