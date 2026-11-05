import { useEffect, useState } from "react";
import { commandsForPrefix, PAGE_COMMANDS, ROUTE_COMMANDS, type WorkspaceCommand } from "./commands";
import { enabledWorkspaceControl, usableWorkspaceControl, workspaceCommandAvailable } from "./commandTargets";

export interface CommandEntry { id: WorkspaceCommand; label: string; group: string; keys: string; context: string }
const ROUTE_LABELS = ["Today", "Radar", "Library", "Interests", "Sources & checks", "Review"];
const WORKSPACE: readonly [WorkspaceCommand, string][] = [
  ["theme-light", "Theme: Light"], ["theme-dark", "Theme: Dark"], ["theme-system", "Theme: System"],
  ["go-preview", "Go to Fictional preview"], ["go-research", "Go to Research a question"],
  ["toggle-sidebar", "Toggle queue & controls"], ["export", "Export notes as Markdown"], ["shortcuts", "Keyboard shortcuts"],
];

/** The live control remains authoritative; rows never retain a DOM callback. */
export function enabledWorkspaceCommands(): CommandEntry[] {
  const scope = document.querySelector<HTMLElement>(".workspace-app");
  if (!scope) return [];
  const rows: CommandEntry[] = [];
  const context = `${location.href}|${scope.querySelector<HTMLElement>(".ws-focus")?.dataset.paperKey ?? ""}|${scope.querySelector(".workspace-review-candidate[data-current='true'] h2 a")?.getAttribute("href") ?? ""}`;
  for (const id of PAGE_COMMANDS) {
    const target = Array.from(scope.querySelectorAll<HTMLElement>(`[data-command="${id}"]`)).find(usableWorkspaceControl);
    if (target) rows.push({ id, label: target.getAttribute("aria-label") || (target instanceof HTMLInputElement ? target.labels?.[0]?.textContent?.trim() : target.textContent?.trim()) || id,
      group: "This page", context, keys: target.getAttribute("aria-keyshortcuts") || "" });
  }
  Object.entries(ROUTE_COMMANDS).forEach(([id, href], index) => {
    const link = scope.querySelector<HTMLElement>(`.ws-navigation a[href="${href}"]`);
    if (!link || usableWorkspaceControl(link)) rows.push({ id: id as keyof typeof ROUTE_COMMANDS,
      label: `Go to ${ROUTE_LABELS[index]}`, group: "Go to", context: "", keys: `G ${["T", "R", "L", "I", "S", "V"][index]}` });
  });
  for (const [id, label] of WORKSPACE) {
    let selector = `[data-command="${id}"]`;
    if (id.startsWith("theme-")) selector = `input[name="theme-preference"][value="${id.slice(6)}"]`;
    if (id === "go-preview" || id === "go-research") selector = `.ws-sidebar-footer a[href="${id === "go-preview" ? "/today" : "/"}"]`;
    if (id === "export") selector = 'a[href="/api/workspace/export"]';
    if (Array.from(scope.querySelectorAll<HTMLElement>(selector)).some(id === "toggle-sidebar" ? usableWorkspaceControl : enabledWorkspaceControl)) {
      rows.push({ id, label, group: "Workspace", context: "", keys: id === "shortcuts" ? "?" : id === "toggle-sidebar" ? "[" : "" });
    }
  }
  return rows;
}

export function filterWorkspaceCommands(query: string): CommandEntry[] {
  const terms = query.replace(/^\//, "").trim().toLowerCase().split(/\s+/);
  return enabledWorkspaceCommands().filter(row => terms.every(term =>
    `${row.label} ${row.id} ${row.group}`.toLowerCase().includes(term)));
}


export function prefixWorkspaceCommands(line: string): CommandEntry[] {
  const rows = enabledWorkspaceCommands();
  return commandsForPrefix(line.replace(/^\//, "")).filter(workspaceCommandAvailable).map(id =>
    rows.find(row => row.id === id) ?? { id, label: id === "escape" ? "Leave search field" : id === "focus-composer" ? "Focus search" : "Open command palette", group: "Workspace", context: "", keys: "" });
}

/** DOM controls can change independently of the composer or the open dialog. */
export function useCommandUpdates(): void {
  const [, update] = useState(0);
  useEffect(() => {
    const scope = document.querySelector(".workspace-app");
    if (!scope) return;
    const observer = new MutationObserver(records => {
      if (records.some(record => {
        const node = record.target instanceof Element ? record.target : record.target.parentElement;
        return !node?.closest(".ws-command-dialog");
      })) update(value => value + 1);
    });
    observer.observe(scope, { subtree: true, childList: true, characterData: true, attributes: true,
      attributeFilter: ["disabled", "aria-disabled", "hidden", "inert", "aria-label", "data-command", "class", "style", "data-rail", "data-viewport", "data-paper-key", "data-current", "data-active", "data-source-request", "href"] });
    return () => observer.disconnect();
  }, []);
}
