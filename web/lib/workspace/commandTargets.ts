import { ROUTE_COMMANDS, type WorkspaceCommand } from "./commands";

export function enabledWorkspaceControl(element: HTMLElement): boolean {
  return element.isConnected && !element.matches(":disabled, [aria-disabled='true']") &&
    !element.closest("[inert], [aria-hidden='true']");
}
export function usableWorkspaceControl(element: HTMLElement): boolean {
  if (!enabledWorkspaceControl(element) || element.closest("[hidden]")) return false;
  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden") return false;
  }
  return true;
}

/** Resolve the current element on every invocation; never retain route controls. */
function control(scope: HTMLElement, selector: string, menu = false): HTMLElement | undefined {
  return Array.from(scope.querySelectorAll<HTMLElement>(selector)).find(menu ? enabledWorkspaceControl : usableWorkspaceControl);
}

type CommandTarget = { element: HTMLElement; action: "click" | "focus" | "blur" } | { href: string };
export function resolveWorkspaceCommand(command: WorkspaceCommand): CommandTarget | null {
  const scope = document.querySelector<HTMLElement>(".workspace-app");
  if (!scope) return null;
  if (command in ROUTE_COMMANDS) {
    const href = ROUTE_COMMANDS[command as keyof typeof ROUTE_COMMANDS];
    const link = scope.querySelector<HTMLElement>(`.ws-navigation a[href="${href}"]`);
    return link ? usableWorkspaceControl(link) ? { element: link, action: "click" } : null : { href };
  }
  if (command === "focus-composer") {
    const input = control(scope, ".ws-composer-input");
    if (input) return { element: input, action: "focus" };
    const opener = control(scope, ".ws-composer-toggle");
    return opener ? { element: opener, action: "click" } : null;
  }
  if (command === "escape") {
    const close = control(scope, '[data-command="escape"]');
    if (close) return { element: close, action: "click" };
    const active = document.activeElement;
    return active instanceof HTMLElement && scope.contains(active) &&
      active.matches('input, textarea, select, [contenteditable]:not([contenteditable="false"])')
      ? { element: active, action: "blur" } : null;
  }
  const selector = command === "go-preview" || command === "go-research"
    ? `.ws-sidebar-footer a[href="${command === "go-preview" ? "/today" : "/"}"]`
    : command.startsWith("theme-")
    ? `input[type="radio"][name="theme-preference"][value="${command.slice(6)}"]`
    : command === "export" ? 'a[href="/api/workspace/export"]' : `[data-command="${command}"]`;
  const target = control(scope, selector, command === "shortcuts" || command === "export" || command === "go-preview" || command === "go-research" || command.startsWith("theme-"));
  return target ? { element: target, action: "click" } : null;
}

export function workspaceCommandAvailable(command: WorkspaceCommand): boolean {
  return resolveWorkspaceCommand(command) !== null;
}
