import type { ReactNode } from "react";

const glyphs = {
  today: <><path d="M2 16h16M4 13h12M6 12a4 4 0 0 1 8 0M10 2v3M3.5 5.5l2 2M16.5 5.5l-2 2" /></>,
  radar: <><circle cx="10" cy="10" r="7" /><circle cx="10" cy="10" r="3.5" /><path d="M10 10l5-5" /></>,
  library: <><path d="M3 4h4v12H3zM8 4h3v12H8zM12 5l3-1 3 11-3 1z" /></>,
  interests: <><circle cx="10" cy="10" r="7" /><circle cx="10" cy="10" r="3" /><path d="M10 10l5-5" /></>,
  sources: <><path d="M16 7a6 6 0 0 0-10-2L4 7M4 3v4h4M4 13a6 6 0 0 0 10 2l2-2M16 17v-4h-4" /></>,
  review: <><rect x="3" y="3" width="14" height="14" rx="2" /><path d="m6 10 3 3 5-6" /></>,
  prev: <><path d="M5 4v12M15 5 8 10l7 5z" /></>,
  next: <><path d="M15 4v12M5 5l7 5-7 5z" /></>,
  open: <><path d="M11 3h6v6M17 3 9 11M15 11v5H4V5h5" /></>,
  save: <path d="M5 3h10v14l-5-3-5 3z" />,
  saved: <path d="M5 3h10v14l-5-3-5 3z" fill="currentColor" />,
  dismiss: <path d="M4 4l12 12M16 4 4 16" />,
  snooze: <path d="M15.5 13A6 6 0 0 1 7 4.5 6.5 6.5 0 1 0 15.5 13z" />,
  undo: <path d="M7 5 3 9l4 4M3 9h8a5 5 0 0 1 5 5" />,
  search: <><circle cx="8.5" cy="8.5" r="5" /><path d="m12.5 12.5 4 4" /></>,
  command: <path d="M7 7V5a2 2 0 1 0-2 2h10a2 2 0 1 0-2-2v10a2 2 0 1 0 2-2H5a2 2 0 1 0 2 2z" />,
  sidebar: <><rect x="3" y="3" width="14" height="14" rx="2" /><path d="M8 3v14" /></>,
  theme: <><circle cx="10" cy="10" r="7" /><path d="M10 3a7 7 0 0 1 0 14z" fill="currentColor" /></>,
  menu: <path d="M3 5h14M3 10h14M3 15h14" />,
  external: <path d="M5 15 15 5M7 5h8v8" />,
  warning: <><path d="M10 3 18 17H2zM10 8v4M10 14.5v.2" /></>,
  plus: <path d="M10 3v14M3 10h14" />,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof glyphs;
export function Icon({ name, className }: { name: IconName; className?: string }) {
  return <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{glyphs[name]}</svg>;
}
