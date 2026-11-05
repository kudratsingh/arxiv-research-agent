"use client";

import { lazy, Suspense, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { dispatchWorkspaceCommand, dispatchWorkspacePrefix } from "@/lib/workspace/dispatch";
import { Icon } from "./Icon";
import { useQueryParam } from "@/lib/workspace/urlState";
import { useSidebarViewport } from "./useSidebarPreference";
import { navigateWorkspace } from "@/lib/workspace/navigation";
import { contextHref, useProductContext } from "@/lib/workspace/productContext";

const CommandSuggestions = lazy(() => import("./WorkspaceDialogs").then(module => ({ default: module.CommandSuggestions })));

export function Composer(): React.ReactElement {
  const context = useProductContext();
  const queryFromURL = useQueryParam("q");
  const [help, setHelp] = useState("");
  const [prefix, setPrefix] = useState("");
  const [open, setOpen] = useState(false);
  const mobile = useSidebarViewport() === "mobile";
  const expanded = !mobile || open;
  const fieldsId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (mobile && open) inputRef.current?.focus();
  }, [mobile, open]);
  function toggle() {
    setOpen(!open);
    if (open) toggleRef.current?.focus();
  }
  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!expanded) return;
    const input = event.currentTarget.elements.namedItem("q");
    if (!(input instanceof HTMLInputElement)) return;
    const query = input.value.trim();
    if (!query) return;
    if (query.startsWith("/")) {
      const suggestions = event.currentTarget.querySelector<HTMLElement>("[data-slash-query]");
      const shown = suggestions?.dataset.slashQuery === query
        ? suggestions.querySelector<HTMLElement>("[data-slash-command]") : null;
      const ran = shown ? shown.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })) : dispatchWorkspacePrefix(query.slice(1));
      if (ran) {
        input.value = "";
        setHelp("");
        setPrefix("");
      } else {
        setHelp("No available command matches. Try another command.");
      }
      return;
    }
    const current = window.location.pathname === "/workspace/radar" ? new URLSearchParams(window.location.search) : new URLSearchParams();
    const params = new URLSearchParams({ q: query, days: current.get("days") ?? (context.mode === "research" ? "0" : "7") });
    for (const key of ["source_id", "access_state", "status"]) {
      const value = current.get(key);
      if (value !== null) params.set(key, value);
    }
    if (!navigateWorkspace(contextHref(`/workspace/radar?${params.toString()}`, context), "paper")) {
      setHelp("Search stayed here. Finish your save or save/copy your draft before leaving.");
    }
  }
  return (
    <form role="search" className="ws-composer ws-composer-shell" data-guarded-navigation="" data-expanded={expanded} onSubmit={submit}>
      <button ref={toggleRef} className="ws-composer-toggle" type="button" hidden={!mobile}
        aria-label={expanded ? "Close search" : "Open search"} aria-expanded={expanded} aria-controls={fieldsId}
        data-command={mobile && expanded ? "escape" : undefined} onClick={toggle}>
        <Icon name={expanded ? "dismiss" : "search"} /><span>{expanded ? "Close" : "Search"}</span>
      </button>
      <div className="ws-composer-fields" id={fieldsId} hidden={!expanded}>
      <input key={queryFromURL ?? ""} defaultValue={queryFromURL ?? ""} ref={inputRef} className="ws-composer-input" type="search" name="q" aria-label="Search stored papers" aria-keyshortcuts="/"
        onChange={(event) => setPrefix(event.currentTarget.value.startsWith("/") ? event.currentTarget.value : "")}
        placeholder="Search stored papers, or /command" aria-describedby={help ? "ws-composer-help" : undefined} />
      <button className="ws-composer-submit" type="submit" title="Search stored papers or run a local /command">Search</button>
      {help && <span className="ws-composer-hint" id="ws-composer-help">{help}</span>}
      </div>
      {expanded && prefix && <Suspense fallback={null}><CommandSuggestions onCommand={dispatchWorkspaceCommand} query={prefix} onChoose={command => { setPrefix(""); if (inputRef.current) { inputRef.current.value = ""; if (command !== "escape") inputRef.current.focus(); } }} /></Suspense>}
    </form>
  );
}
