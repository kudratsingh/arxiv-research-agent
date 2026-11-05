import { prefixWorkspaceCommands, useCommandUpdates } from "@/lib/workspace/commandRegistry";
import type { WorkspaceCommand } from "@/lib/workspace/commands";

export default function CommandSuggestions({ query, onChoose, onCommand }: { query: string; onChoose: (command: WorkspaceCommand) => void; onCommand: (command: WorkspaceCommand) => boolean }) {
  useCommandUpdates();
  const rows = prefixWorkspaceCommands(query).slice(0, 6);
  return <div className="ws-command-dialog ws-command-suggestions" data-slash-query={query} role="region" aria-label="Available local commands">
    {rows.length ? rows.map((row, index) => <button className="ws-queue-row" type="button" key={row.id} data-slash-command={row.id} onMouseDown={event => event.preventDefault()} onClick={event => {
      if (prefixWorkspaceCommands(query).some(current => current.id === row.id && current.label === row.label && current.context === row.context) && onCommand(row.id)) onChoose(row.id);
      else event.preventDefault();
    }}><span>{row.label}</span><kbd aria-hidden="true">{index === 0 ? "Enter" : row.keys}</kbd></button>)
      : <p>No available command matches.</p>}
  </div>;
}
