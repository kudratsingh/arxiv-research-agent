"use client";
import Link from "next/link";
import { Announcement } from "./Announcement";
import { useState, useSyncExternalStore } from "react";
import type { WorkspaceItem } from "@/lib/daily/fixtures";
import { usePreview } from "./state";

const subscribeHash = (listener: () => void) => {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
};
const getHash = () => window.location.hash.slice(1);
export function Reader({ item }: { item: WorkspaceItem }) {
  const { data, storage, update } = usePreview();
  const hash = useSyncExternalStore(subscribeHash, getHash, () => "");
  const active = ["source", "understand", "notes"].includes(hash)
    ? hash
    : (data.anchors[item.id] ?? "source");
  const [body, setBody] = useState(item.prompt);
  const [kind, setKind] = useState<"question" | "note" | "next-action">(
    "question",
  );
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const entries = data.entries.filter((entry) => entry.itemId === item.id);
  const saved = data.saved.includes(item.id);
  return (
    <>
      <div className="daily-page-meta">
        <Link href="/today" prefetch={false} className="daily-link">
          ← Today
        </Link>
        <span className="daily-eyebrow">
          Source reader · fictional material
        </span>
      </div>
      <header className="daily-reader-header">
        <div className="daily-item-meta">
          <span>{item.kind}</span>
          <span>{item.version}</span>
          <span>
            {item.scope === "abstract"
              ? "Abstract only"
              : item.scope === "excerpt"
                ? "Source excerpt"
                : "Metadata only"}
          </span>
        </div>
        <h1>{item.title}</h1>
        <p>
          {item.source} · {item.published}
        </p>
        <button
          className="daily-secondary"
          aria-pressed={saved}
          onClick={() =>
            update((d) => ({
              ...d,
              saved: saved
                ? d.saved.filter((id) => id !== item.id)
                : [...d.saved, item.id],
            }))
          }
        >
          {saved ? "Remove from saved items" : "Save to Library"}
        </button>
      </header>
      <nav className="daily-reader-tabs" aria-label="Reading sections">
        {[
          ["source", "Source"],
          ["understand", "Understand"],
          ["notes", "Your notes"],
        ].map(([id, label]) => (
          <a
            key={id}
            href={`#${id}`}
            aria-current={active === id ? "location" : undefined}
            onClick={() =>
              update((d) => ({
                ...d,
                anchors: { ...d.anchors, [item.id]: id! },
              }))
            }
          >
            {label}
          </a>
        ))}
      </nav>
      <div className="daily-reader-grid">
        <section
          id="source"
          className="daily-source-panel"
          data-active={active === "source"}
          aria-labelledby="source-title"
        >
          <div className="daily-section-heading">
            <h2 id="source-title">
              {item.scope === "abstract"
                ? "Source abstract"
                : item.scope === "excerpt"
                  ? "Source excerpt"
                  : "Source record"}
            </h2>
            <span>{item.version}</span>
          </div>
          <p className="daily-source-attribution">
            Fictional text written for this preview. It is not a generated
            summary of a real paper.
          </p>
          <div className="daily-source-text">
            <p>{item.abstract}</p>
          </div>
          <div className="daily-source-boundary">
            <span className="daily-eyebrow">What you can establish</span>
            <p>{item.caveat}</p>
            <p>
              No methods, result tables or full-text passages have been
              acquired. An original-source link will appear for a real imported
              work; this fixture has no external original.
            </p>
          </div>
        </section>
        <aside
          className="daily-understand-panel"
          id="understand"
          data-active={active === "understand"}
          aria-labelledby="understand-title"
        >
          <span className="daily-eyebrow">Understand this work</span>
          <h2 id="understand-title">
            Start with what
            <br />
            the source supports.
          </h2>
          <p>{item.reason}</p>
          <div className="daily-thread">
            <div>
              <span>A useful question</span>
              <p>{item.prompt}</p>
            </div>
            <div>
              <span>Evidence boundary</span>
              <p>
                The available {item.scope} does not establish the full
                experimental procedure. Keep that gap attached to your notes.
              </p>
            </div>
            <div>
              <span>Test next · proposal</span>
              <p>
                {item.nextAction}
              </p>
            </div>
          </div>
          <div className="daily-generation">
            <h3>Guided deep dive</h3>
            <p>
              Grounded explanations, comparisons and build briefs will use
              retained passages and an approved model budget.
            </p>
            <button className="daily-secondary" disabled>
              Generation not enabled
            </button>
            <p className="daily-muted">
              Source reading and your notes remain available.
            </p>
          </div>
        </aside>
        <section
          id="notes"
          className="daily-notes-panel"
          data-active={active === "notes"}
          aria-labelledby="notes-title"
        >
          <div>
            <span className="daily-eyebrow">Your own thinking</span>
            <h2 id="notes-title">Keep a question open.</h2>
            <p>
              Save your words against this source version. A question is not a
              new research job.
            </p>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!body.trim()) return;
              update((d) => ({
                ...d,
                saved: Array.from(new Set([...d.saved, item.id])),
                anchors: { ...d.anchors, [item.id]: "notes" },
                entries: editing
                  ? d.entries.map((entry) =>
                      entry.id === editing
                        ? { ...entry, kind, body: body.trim() }
                        : entry,
                    )
                  : [
                      ...d.entries,
                      {
                        id: crypto.randomUUID(),
                        itemId: item.id,
                        kind,
                        body: body.trim(),
                        anchor: "source",
                      },
                    ],
              }));
              setNotice(
                editing
                  ? "Updated your research thread."
                  : "Added to your research thread.",
              );
              setEditing(null);
              setBody("");
            }}
          >
            <label>
              Save as
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as typeof kind)}
              >
                <option value="question">Question</option>
                <option value="note">Note</option>
                <option value="next-action">Next action</option>
              </select>
            </label>
            <label>
              Your {kind.replace("-", " ")}
              <textarea
                maxLength={4000}
                rows={4}
                value={body}
                onChange={(e) => {
                  setBody(e.target.value);
                  setNotice("");
                }}
              />
            </label>
            <div className="daily-form-footer">
              <span>
                Linked to {item.version} · {item.scope}
              </span>
              <button className="daily-button" disabled={!body.trim()}>
                {editing ? "Update" : "Save"} {kind.replace("-", " ")}
              </button>
            </div>
            <Announcement>
              {notice &&
                (storage === "unavailable"
                  ? "Added in this tab only. Browser storage is unavailable; export your notes before leaving."
                  : `${notice} Saved in this browser.`)}
            </Announcement>
          </form>
          {entries.length > 0 && (
            <div className="daily-saved-entries">
              <h3>Saved from this source</h3>
              {entries.map((entry) => (
                <article key={entry.id}>
                  <span className="daily-eyebrow">
                    Your {entry.kind.replace("-", " ")}
                  </span>
                  <p>{entry.body}</p>
                  <a className="daily-link" href="#source">
                    Source · {item.version}
                  </a>
                  <button
                    type="button"
                    className="daily-text-button"
                    onClick={() => {
                      setEditing(entry.id);
                      setBody(entry.body);
                      setKind(entry.kind);
                      setNotice("");
                      document
                        .querySelector<HTMLTextAreaElement>("#notes textarea")
                        ?.focus();
                    }}
                  >
                    Edit {entry.kind.replace("-", " ")}
                  </button>
                </article>
              ))}
              <Link className="daily-link" href="/today" prefetch={false}>
                Return to Today with this thread →
              </Link>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
