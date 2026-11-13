"use client";
import Link from "next/link";
import { Announcement } from "./Announcement";
import { useState } from "react";
import { STREAMS } from "@/lib/daily/profile";
import { PRESET } from "@/lib/daily/fixtures";
import { usePreview } from "./state";

type Topic = { id: string; label: string; kind: string; parents: string[] };
export function Interests({ topics }: { topics: Topic[] }) {
  const { data, storage, update } = usePreview();
  const [query, setQuery] = useState("");
  const [field, setField] = useState("");
  const [custom, setCustom] = useState("");
  const [question, setQuestion] = useState<string | null>(null);
  const [questionSaved, setQuestionSaved] = useState(false);
  const fields = topics.filter((t) => t.kind === "external_field");
  const inField = (topic: Topic, id: string): boolean =>
    topic.id === id ||
    topic.parents.some(
      (parent) =>
        parent === id || topics.some((t) => t.id === parent && inField(t, id)),
    );
  const visible = topics.filter(
    (t) =>
      (query
        ? `${t.label} ${t.id}`.toLowerCase().includes(query.toLowerCase())
        : !!field ||
          t.kind === "authored_ml_group" ||
          t.kind === "external_field") &&
      (!field || inField(t, field)),
  );
  return (
    <>
      <div className="daily-page-meta">
        <span className="daily-eyebrow">Your research lens</span>
        <Link href="/today" prefetch={false} className="daily-link">
          Back to Today →
        </Link>
      </div>
      <div className="daily-intro">
        <div>
          <h1>
            Follow a field.
            <br />
            <em>Or your own question.</em>
          </h1>
          <p>Start narrow, explore widely. Your choices stay editable.</p>
        </div>
      </div>
      <section id="streams" className="daily-lens">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            update((d) => ({
              ...d,
              researchQuestion: (question ?? data.researchQuestion).trim(),
            }));
            setQuestionSaved(true);
          }}
        >
          <label>
            Your current research question
            <textarea
              rows={3}
              maxLength={2000}
              value={question ?? data.researchQuestion}
              onChange={(e) => {
                setQuestion(e.target.value);
                setQuestionSaved(false);
              }}
            />
          </label>
          <button className="daily-secondary">Save research question</button>
          {questionSaved && (
            <Announcement>
              {storage === "unavailable"
                ? "Saved for this tab only."
                : "Research question saved in this browser."}
            </Announcement>
          )}
        </form>
        <fieldset>
          <legend>Your research streams</legend>
          {STREAMS.map((stream) => (
            <label key={stream.id}>
              <input
                type="checkbox"
                checked={data.streams.includes(stream.id)}
                onChange={() =>
                  update((d) => ({
                    ...d,
                    streams: d.streams.includes(stream.id)
                      ? d.streams.filter((id) => id !== stream.id)
                      : [...d.streams, stream.id],
                  }))
                }
              />
              <span>
                <strong>{stream.label}</strong>
                <small>{stream.detail}</small>
                <small>Source connections not enabled</small>
              </span>
            </label>
          ))}
        </fieldset>
      </section>
      <div className="daily-interests-grid">
        <section>
          <h2>Explore interests</h2>
          <p>
            384 catalogue entries · 26 field anchors · no live connectors
            enabled
          </p>
          <div className="daily-filters">
            <label>
              Search topics
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Try retrieval, neuroscience, economics…"
              />
            </label>
            <label>
              Broad field
              <select
                value={field}
                onChange={(e) => {
                  setField(e.target.value);
                  setQuery("");
                }}
              >
                <option value="">All fields</option>
                {fields.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="daily-muted">
            {visible.length} matching entries. Search for detailed topics or
            browse a field.
          </p>
          <div className="daily-topic-list">
            {visible.map((topic) => (
              <label key={topic.id}>
                <input
                  type="checkbox"
                  checked={data.topics.includes(topic.id)}
                  onChange={() =>
                    update((d) => ({
                      ...d,
                      configured: true,
                      topics: d.topics.includes(topic.id)
                        ? d.topics.filter((id) => id !== topic.id)
                        : [...d.topics, topic.id],
                    }))
                  }
                />
                <span>
                  <strong>{topic.label}</strong>
                  <small>
                    {topic.kind === "external_field"
                      ? "OpenAlex field anchor"
                      : "Authored study topic"}{" "}
                    · coverage not connected
                  </small>
                </span>
              </label>
            ))}
          </div>
        </section>
        <aside className="daily-interest-summary">
          <span className="daily-eyebrow">Selected lens</span>
          <h2>{data.topics.length + data.customTopics.length} interests</h2>
          <button
            className="daily-secondary"
            onClick={() =>
              update((d) => ({ ...d, configured: true, topics: PRESET }))
            }
          >
            Use suggested ML lens
          </button>
          <ul>
            {data.topics.map((id) => (
              <li key={id}>
                {topics.find((t) => t.id === id)?.label ?? id}
                <button
                  onClick={() =>
                    update((d) => ({
                      ...d,
                      configured: true,
                      topics: d.topics.filter((t) => t !== id),
                    }))
                  }
                  aria-label={`Remove ${topics.find((t) => t.id === id)?.label ?? id}`}
                >
                  ×
                </button>
              </li>
            ))}
            {data.customTopics.map((name) => (
              <li key={name}>
                {name}
                <button
                  aria-label={`Remove ${name}`}
                  onClick={() =>
                    update((d) => ({
                      ...d,
                      customTopics: d.customTopics.filter((t) => t !== name),
                    }))
                  }
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const value = custom.trim();
              if (value) {
                update((d) => ({
                  ...d,
                  configured: true,
                  customTopics: Array.from(new Set([...d.customTopics, value])),
                }));
                setCustom("");
              }
            }}
          >
            <label>
              Your own topic or question
              <input
                maxLength={200}
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                placeholder="A question you want to follow"
              />
            </label>
            <button className="daily-secondary" disabled={!custom.trim()}>
              Add custom interest
            </button>
          </form>
          <p>
            {storage === "unavailable"
              ? "Changes are only in this open tab. Browser storage is unavailable."
              : "Choices saved in this browser. Custom interests will need source coverage before live matching."}
          </p>
          <Link className="daily-button" href="/today" prefetch={false}>
            See your sample briefing →
          </Link>
        </aside>
      </div>
    </>
  );
}
