import { useEffect, useId, useRef, useState } from "react";
import { enabledWorkspaceCommands, filterWorkspaceCommands, useCommandUpdates, type CommandEntry } from "@/lib/workspace/commandRegistry";
import type { WorkspaceCommand } from "@/lib/workspace/commands";

export interface WorkspaceDialogRequest { kind: "palette" | "shortcuts"; invoker: HTMLElement | null }

export default function WorkspaceDialogs({ request, onClose, onCommand }: { request: WorkspaceDialogRequest; onClose: () => void; onCommand: (command: WorkspaceCommand) => boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(() => filterWorkspaceCommands("")[0] ?? null);
  useCommandUpdates();
  const title = useId();
  const list = useId();
  const palette = request.kind === "palette";
  const rows = filterWorkspaceCommands(query);
  const index = rows.findIndex(row => row.id === selected?.id && row.label === selected.label && row.context === selected.context);
  useEffect(() => {
    const node = dialog.current!;
    if (typeof node.showModal === "function") node.showModal();
    else node.setAttribute("open", "");
    (search.current ?? node.querySelector<HTMLElement>("button"))?.focus();
    return () => { if (request.invoker?.isConnected) request.invoker.focus({ preventScroll: true }); };
  }, [request]);

  function close(entry?: CommandEntry) {
    if (typeof dialog.current?.close === "function") dialog.current.close();
    onClose();
    // Re-resolve only after modal dismissal; guards and current disabled states win.
    if (entry) setTimeout(() => {
      if (enabledWorkspaceCommands().some(row => row.id === entry.id && row.label === entry.label && row.context === entry.context)) onCommand(entry.id);
    }, 0);
  }
  return <dialog ref={dialog} className="ws-command-dialog" data-workspace-palette={palette ? "" : undefined} aria-labelledby={title}
    onCancel={event => { event.preventDefault(); close(); }} onKeyDown={event => {
      if (event.nativeEvent.isComposing) return;
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
      if (event.key === "Tab" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        const first = dialog.current!.querySelector<HTMLButtonElement>("button")!;
        const last = search.current ?? first;
        if (event.shiftKey ? document.activeElement === first : document.activeElement === last) {
          event.preventDefault();
          (event.shiftKey ? last : first).focus();
        }
      }
    }}>
    <header className="ws-side-heading"><h2 id={title}>{palette ? "Commands" : "Keyboard shortcuts"}</h2>
      <button type="button" className="ws-sidebar-toggle ws-dialog-close" onClick={() => close()}>Close <kbd aria-hidden="true">Esc</kbd></button></header>
    {palette ? <>
      <label className="sr-only" htmlFor={`${list}-search`}>Find a command</label>
      <input ref={search} id={`${list}-search`} role="combobox" aria-autocomplete="list" aria-expanded="true"
        aria-controls={list} aria-activedescendant={rows[index] ? `${list}-${index}` : undefined}
        placeholder="Find a command…" value={query} onChange={event => { setQuery(event.currentTarget.value); setSelected(filterWorkspaceCommands(event.currentTarget.value)[0] ?? null); }}
        onKeyDown={event => {
          if (event.nativeEvent.isComposing) return;
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            const next = rows.length ? index < 0 ? event.key === "ArrowDown" ? 0 : rows.length - 1 : (index + (event.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length : -1;
            setSelected(rows[next] ?? null);
            document.getElementById(`${list}-${next}`)?.scrollIntoView?.({ block: "nearest" });
          } else if (event.key === "Enter") { event.preventDefault(); if (rows[index]) close(rows[index]); }
        }} />
      <ul className="ws-queue" role="listbox" tabIndex={-1} id={list} aria-label="Available commands">{rows.map((row, position) => <li role="presentation" key={row.id}>
        <button className="ws-queue-row" type="button" role="option" id={`${list}-${position}`} aria-selected={position === index} aria-label={row.label}
          tabIndex={-1} onMouseDown={event => event.preventDefault()} onClick={() => close(row)}>
          <span className="ws-queue-text"><span className="ws-queue-title">{row.label}</span><small className="ws-queue-meta">{row.group}</small></span><kbd aria-hidden="true">{row.keys}</kbd>
        </button></li>)}</ul>
      {!rows.length && <p>No available commands match. Try another search.</p>}
    </> : <>
      <p>Shortcuts act on the current paper or candidate. Typing in a form keeps its normal keys.</p>
      <dl className="ws-shortcuts-list"><div><dt><kbd>⌘K / Ctrl K</kbd></dt><dd>Open commands</dd></div>
        <div><dt><kbd>/</kbd></dt><dd>Focus search; type /command for local actions</dd></div>
        {rows.filter(row => row.keys).map(row => <div key={row.id}><dt><kbd>{row.keys}</kbd></dt><dd>{row.label}</dd></div>)}
        <div><dt><kbd>Esc</kbd></dt><dd>Close dialog or controls; leave a text field</dd></div></dl>
      <p className="daily-muted">Only currently available page actions are listed. Use the visible controls at any time.</p>
    </>}
  </dialog>;
}

export { default as CommandSuggestions } from "./CommandSuggestions";
