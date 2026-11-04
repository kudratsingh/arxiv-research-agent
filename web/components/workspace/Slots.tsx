"use client";

import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

interface SlotTargets { sidebar: HTMLElement | null; header: HTMLElement | null; bar: HTMLElement | null }
const SlotContext = createContext<SlotTargets | null>(null);

/** Pages retain their data and handlers; the Shell supplies only destinations. */
export function WorkspaceSlots({ children, ...targets }: SlotTargets & { children: ReactNode }) {
  return <SlotContext.Provider value={targets}>{children}</SlotContext.Provider>;
}

function Slot({ target, children }: { target: keyof SlotTargets; children: ReactNode }) {
  const slots = useContext(SlotContext);
  if (!slots) return children;
  const node = slots[target];
  return node ? createPortal(children, node) : null;
}

export function SidebarSection({ label, children }: { label: string; children: ReactNode }) {
  return <Slot target="sidebar"><section className="ws-side-section" aria-label={label}>{children}</section></Slot>;
}

/** Portaled submit controls must retain their native form="id" association. */
export function ControlBar({ children }: { children: ReactNode }) {
  return <Slot target="bar">{children}</Slot>;
}

export function StageHeaderSlot({ position, sources, action, children }: {
  position?: { n: number; N: number };
  sources?: { ok: number; total: number; worst?: "ok" | "limited" | "failed" };
  action?: ReactNode;
  children?: ReactNode;
}) {
  return <Slot target="header"><div className="ws-header-content">
    {position && <span className="ws-position" aria-label={`Paper ${position.n} of ${position.N}`}>
      {String(position.n).padStart(2, "0")} / {String(position.N).padStart(2, "0")}
    </span>}
    {sources && <span className="ws-source-summary" data-source-state={sources.worst}>
      <span className="ws-source-dot" aria-hidden="true" />
      {sources.ok}/{sources.total} sources{sources.worst && sources.worst !== "ok" ? ` · ${sources.worst}` : ""}
    </span>}
    {action && <div className="ws-header-action">{action}</div>}
    {children}
  </div></Slot>;
}
