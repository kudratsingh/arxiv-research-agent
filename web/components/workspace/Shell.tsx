"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/patterns/ThemeToggle";
import { SkipLink } from "@/components/primitives/SkipLink";
import "@/components/daily/daily.css";
import "./workspace.css";

const NAVIGATION = [
  ["today", "Today", "◷"],
  ["radar", "Radar", "⌕"],
  ["library", "Library", "▤"],
  ["interests", "Interests", "◎"],
  ["operations", "Sources & checks", "↻"],
];

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <div className="daily-app workspace-app font-ui">
      <SkipLink />
      <header className="daily-header">
        <Link href="/workspace/today" prefetch={false} className="daily-brand">
          <span className="daily-brand-mark" aria-hidden="true">
            r<span>·</span>
          </span>
          <span>
            Research workspace
            <span className="daily-brand-sub">
              A place to follow a question.
            </span>
          </span>
        </Link>
        <div className="daily-header-actions">
          <ThemeToggle />
          <Link className="daily-link" href="/today" prefetch={false}>
            Fictional preview ↗
          </Link>
        </div>
      </header>
      <div className="daily-preview-bar workspace-mode">
        <span className="daily-dot" aria-hidden="true" />
        <strong>Local workspace</strong>
        <span>
          Real source metadata · private server saves · generation off
        </span>
      </div>
      <div className="daily-frame">
        <aside className="daily-sidebar">
          <nav aria-label="Research workspace">
            {NAVIGATION.map(([slug, label, icon]) => {
              const href = `/workspace/${slug}`;
              return (
                <Link
                  key={slug}
                  href={href}
                  prefetch={false}
                  aria-current={path.startsWith(href) ? "page" : undefined}
                >
                  <span aria-hidden="true">{icon}</span>
                  {label}
                </Link>
              );
            })}
          </nav>
          <div className="daily-sidebar-note">
            <span className="daily-eyebrow">Your workspace</span>
            <p>
              Discover. Understand.
              <br />
              Keep the thread.
            </p>
            <Link href="/" prefetch={false}>
              Research a question ↗
            </Link>
          </div>
          <p className="daily-storage">
            Notes belong to your local account. A failed save stays a draft; it
            is never labelled saved.
          </p>
        </aside>
        <main id="main" tabIndex={-1} className="daily-main">
          {children}
        </main>
      </div>
    </div>
  );
}
