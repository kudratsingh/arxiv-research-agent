"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { dispatchWorkspacePrefix } from "@/lib/workspace/dispatch";
import { Icon } from "./Icon";
import { useSidebarViewport } from "./useSidebarPreference";

export function Composer(): React.ReactElement {
  const [help, setHelp] = useState("");
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
      if (dispatchWorkspacePrefix(query.slice(1))) {
        input.value = "";
        setHelp("");
      } else {
        setHelp("No available command matches. Try another command.");
      }
      return;
    }
    const params = new URLSearchParams({ q: query, days: "7" });
    // Full navigation preserves the existing route contract without a router dependency.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    location.assign(`/workspace/radar?${params.toString()}`);
  }
  return (
    <form role="search" className="ws-composer ws-composer-shell" data-expanded={expanded} onSubmit={submit}>
      <button ref={toggleRef} className="ws-composer-toggle" type="button" hidden={!mobile}
        aria-label={expanded ? "Close search" : "Open search"} aria-expanded={expanded} aria-controls={fieldsId}
        data-command={mobile && expanded ? "escape" : undefined} onClick={toggle}>
        <Icon name={expanded ? "dismiss" : "search"} /><span>{expanded ? "Close" : "Search"}</span>
      </button>
      <div className="ws-composer-fields" id={fieldsId} hidden={!expanded}>
      <input ref={inputRef} className="ws-composer-input" type="search" name="q" aria-label="Search stored papers" aria-keyshortcuts="/"
        placeholder="Search stored papers, or /command" aria-describedby={help ? "ws-composer-help" : undefined} />
      <button className="ws-composer-submit" type="submit" title="Search stored papers or run a local /command">Search</button>
      {help && <span className="ws-composer-hint" id="ws-composer-help">{help}</span>}
      </div>
    </form>
  );
}
