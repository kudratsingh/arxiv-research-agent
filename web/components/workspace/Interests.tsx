"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import topicsSeed from "@/lib/daily/topics.json";
import { STREAMS } from "@/lib/daily/profile";
import {
  errorMessage,
  requestId,
  workspaceRequest,
  type ProfileData,
} from "@/lib/workspace/api";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { LoadingState, Message, ServiceNotice } from "./Common";

const topics = topicsSeed.topics;
function lines(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export function LiveInterests() {
  const { state, error, reload } = useWorkspace();
  const [draft, setDraft] = useState<ProfileData | null>(null);
  const [baseRevision, setBaseRevision] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [field, setField] = useState("");
  const [customRaw, setCustomRaw] = useState<string | null>(null);
  const [exclusionsRaw, setExclusionsRaw] = useState<string | null>(null);
  const attempts = useRef(new Map<string, string>());
  if (!state) return <LoadingState error={error} retry={() => void reload()} />;
  const data = draft ?? state.profile.data;
  const fields = topics.filter((topic) => topic.kind === "external_field");
  const inField = (id: string, parent: string): boolean =>
    id === parent ||
    (topics
      .find((topic) => topic.id === id)
      ?.parents.some((candidate) => inField(candidate, parent)) ??
      false);
  const visible = topics.filter(
    (topic) =>
      (query
        ? `${topic.id} ${topic.label}`
            .toLowerCase()
            .includes(query.toLowerCase())
        : Boolean(field) ||
          ["authored_ml_group", "external_field"].includes(topic.kind)) &&
      (!field || inField(topic.id, field)),
  );
  function change(next: Partial<ProfileData>) {
    if (!state) return;
    if (draft === null) setBaseRevision(state.profile.revision);
    setDraft({ ...(draft ?? state.profile.data), ...next });
    setNotice("You have unsaved interest changes.");
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!state) return;
    const payload = {
      revision: baseRevision ?? state.profile.revision,
      data: {
        ...data,
        custom_topics:
          customRaw === null ? data.custom_topics : lines(customRaw),
        exclusions:
          exclusionsRaw === null ? data.exclusions : lines(exclusionsRaw),
      },
    };
    const fingerprint = JSON.stringify(payload),
      id = attempts.current.get(fingerprint) ?? requestId();
    attempts.current.set(fingerprint, id);
    setBusy(true);
    try {
      await workspaceRequest("profile", { ...payload, request_id: id });
      await workspaceRequest("edition", {});
      await reload();
      setDraft(null);
      setBaseRevision(null);
      setCustomRaw(null);
      setExclusionsRaw(null);
      setNotice(
        "Interests and research question saved on the server. A new edition uses this revision; earlier editions remain unchanged.",
      );
    } catch (failure) {
      setNotice(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="daily-page-meta">
        <span className="daily-eyebrow">
          Your research lens · revision {state.profile.revision}
        </span>
        <Link className="daily-link" href="/workspace/today" prefetch={false}>
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
          <p>
            Explicit interests shape the next briefing. Your preferences stay
            editable.
          </p>
        </div>
      </div>
      <ServiceNotice error={error} />
      <form onSubmit={(event) => void save(event)}>
        <section className="daily-lens">
          <div>
            <label>
              Your current research question
              <textarea
                rows={4}
                maxLength={2000}
                value={data.research_question}
                onChange={(event) =>
                  change({ research_question: event.target.value })
                }
              />
            </label>
            <label>
              Daily reading window
              <select
                value={data.minutes}
                onChange={(event) =>
                  change({ minutes: Number(event.target.value) as 5 | 15 | 45 })
                }
              >
                <option value={5}>5 minutes</option>
                <option value={15}>15 minutes</option>
                <option value={45}>45 minutes</option>
              </select>
            </label>
          </div>
          <fieldset>
            <legend>Your research streams</legend>
            {STREAMS.map((stream) => (
              <label key={stream.id}>
                <input
                  type="checkbox"
                  checked={data.streams.includes(stream.id)}
                  onChange={() =>
                    change({
                      streams: data.streams.includes(stream.id)
                        ? data.streams.filter((id) => id !== stream.id)
                        : [...data.streams, stream.id],
                    })
                  }
                />
                <span>
                  {stream.label}
                  <small>{stream.detail}</small>
                </span>
              </label>
            ))}
            <p className="daily-muted">
              Rocket Twin and spatial work have limited coverage in the
              currently connected ML/lab sources. A selected stream is not a
              claim of comprehensive monitoring.
            </p>
          </fieldset>
        </section>
        <div className="daily-interests-grid">
          <section>
            <div className="daily-section-heading">
              <h2>Fields and detailed topics</h2>
              <span>
                {topics.length} catalogue entries · {fields.length} field
                anchors
              </span>
            </div>
            <p className="daily-muted">
              The broad catalogue is navigation. Active intake covers only arXiv
              cs.LG/cs.AI/cs.CL, Hugging Face Blog and Google Research Blog.
            </p>
            <div className="daily-filters">
              <label>
                Find a topic
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Retrieval, control, evaluation…"
                />
              </label>
              <label>
                Browse a field
                <select
                  value={field}
                  onChange={(event) => setField(event.target.value)}
                >
                  <option value="">All fields</option>
                  {fields.map((topic) => (
                    <option key={topic.id} value={topic.id}>
                      {topic.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="daily-topic-list">
              {visible.map((topic) => (
                <label key={topic.id}>
                  <input
                    type="checkbox"
                    checked={data.topics.includes(topic.id)}
                    onChange={() =>
                      change({
                        topics: data.topics.includes(topic.id)
                          ? data.topics.filter((id) => id !== topic.id)
                          : [...data.topics, topic.id],
                      })
                    }
                  />
                  <span>
                    <strong>{topic.label}</strong>
                    <small>
                      {topic.kind.startsWith("external")
                        ? "Scholarly catalogue · connected coverage varies"
                        : "Authored study topic · exact term matches where available"}
                    </small>
                  </span>
                </label>
              ))}
              {visible.length === 0 && (
                <p>No catalogue entries match. Add a custom interest.</p>
              )}
            </div>
          </section>
          <aside className="daily-interest-summary">
            <h2>Your terms and boundaries</h2>
            <label>
              Custom interests or watch terms
              <span className="workspace-topic-count">One term per line</span>
              <textarea
                rows={5}
                value={customRaw ?? data.custom_topics.join("\n")}
                onChange={(event) => {
                  setCustomRaw(event.target.value);
                  change({});
                }}
                placeholder="agent memory&#10;sim-to-real control"
              />
            </label>
            <label>
              Exclude these terms
              <span className="workspace-topic-count">
                Exclusions take priority over positive matches
              </span>
              <textarea
                rows={4}
                value={exclusionsRaw ?? data.exclusions.join("\n")}
                onChange={(event) => {
                  setExclusionsRaw(event.target.value);
                  change({});
                }}
              />
            </label>
            <label>
              Exploration allocation
              <select
                value={data.exploration}
                onChange={(event) =>
                  change({ exploration: Number(event.target.value) })
                }
              >
                <option value={0}>0% · only explicit matches</option>
                <option value={0.15}>Up to 15% · adjacent source items</option>
                <option value={0.3}>Up to 30% · broader exploration</option>
              </select>
            </label>
            <p>
              {data.topics.length} topics selected. Ranking shows the actual
              matching terms. Opening a paper does not rewrite your declared
              interests.
            </p>
          </aside>
        </div>
        <div className="workspace-toolbar">
          <button className="daily-button" disabled={busy}>
            {busy ? "Saving interests…" : "Save interests and question"}
          </button>
          {draft && (
            <button
              type="button"
              className="daily-secondary"
              onClick={() => {
                setDraft(null);
                setBaseRevision(null);
                setCustomRaw(null);
                setExclusionsRaw(null);
                void reload();
                setNotice(
                  "Draft discarded at your request. Loading the saved server profile.",
                );
              }}
            >
              Discard draft and reload saved profile
            </button>
          )}
          <Message>{notice}</Message>
        </div>
      </form>
    </>
  );
}
