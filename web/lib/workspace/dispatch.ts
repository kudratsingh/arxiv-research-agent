import { navigateWorkspace } from "./navigation";
import { allowWorkspaceNavigation } from "./navigationGuard";
import { commandsForPrefix, type WorkspaceCommand } from "./commands";
import { resolveWorkspaceCommand } from "./commandTargets";

export function dispatchWorkspaceCommand(command: WorkspaceCommand): boolean {
  if (document.querySelector(".ws-command-dialog[open]")) return false;
  const target = resolveWorkspaceCommand(command);
  if (!target) return false;
  if ("href" in target) return navigateWorkspace(target.href);
  if (target.element instanceof HTMLAnchorElement && !target.element.hasAttribute("download") && target.element.target !== "_blank" && !target.element.getAttribute("href")?.startsWith("#") && !allowWorkspaceNavigation(target.element.href)) return false;
  target.element[target.action]();
  return true;
}

/** Interpret human-readable aliases, then resolve against the current controls. */
export function dispatchWorkspacePrefix(line: string): boolean {
  return commandsForPrefix(line).some(dispatchWorkspaceCommand);
}
