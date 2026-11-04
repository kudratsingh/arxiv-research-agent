"use client";

import { useState, type FormEvent } from "react";
import { dispatchWorkspacePrefix } from "@/lib/workspace/dispatch";

export function Composer(): React.ReactElement {
  const [help, setHelp] = useState("");
  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
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
    <form role="search" className="ws-composer" onSubmit={submit}>
      <input className="ws-composer-input" type="search" name="q" aria-label="Search stored papers" aria-keyshortcuts="/"
        placeholder="Search stored papers, or /command" aria-describedby={help ? "ws-composer-help" : undefined} />
      <button className="ws-composer-submit" type="submit" title="Search stored papers or run a local /command">Search</button>
      {help && <span className="ws-composer-hint" id="ws-composer-help">{help}</span>}
    </form>
  );
}
