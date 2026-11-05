import { requestWorkspaceNavigation } from "./navigation";
import { commandsForPrefix, type WorkspaceCommand } from "./commands";
import { resolveWorkspaceCommand } from "./commandTargets";

export function dispatchWorkspaceCommand(command: WorkspaceCommand): boolean {
  if (document.querySelector(".ws-command-dialog[open]")) return false;
  const target = resolveWorkspaceCommand(command);
  if (!target) return false;
  if ("href" in target) { requestWorkspaceNavigation(target.href); location.assign(target.href); }
  else target.element[target.action]();
  return true;
}

/** Interpret human-readable aliases, then resolve against the current controls. */
export function dispatchWorkspacePrefix(line: string): boolean {
  return commandsForPrefix(line).some(dispatchWorkspaceCommand);
}
