"use client";

import { useState } from "react";
import topicsSeed from "@/lib/daily/topics.json";
import type { WorkspaceState } from "@/lib/workspace/api";

const topics = topicsSeed.topics;

/** The catalogue loads separately; editing the question never waits for its data. */
export default function InterestTopics({ selected, coverage, onChange }: {
  selected: string[];
  coverage: WorkspaceState["interest_coverage"];
  onChange: (topics: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [field, setField] = useState("");
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
  return <>
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
                    checked={selected.includes(topic.id)}
                    onChange={() =>
                      onChange(selected.includes(topic.id)
                          ? selected.filter((id) => id !== topic.id)
                          : [...selected, topic.id])
                    }
                  />
                  <span>
                    <strong>{topic.label}</strong>
                    <small>
                      {topic.kind.startsWith("external")
                        ? "Scholarly catalogue · navigation is separate from monitoring"
                        : selected.includes(topic.id)
                          ? coverage.find(
                              (coverage) => coverage.topic_id === topic.id,
                            )?.matching_mode === "browse_only"
                            ? "Browse only · no matching terms configured"
                            : coverage.some(
                                  (coverage) => coverage.topic_id === topic.id,
                                )
                              ? "Saved matching vocabulary · inspect its terms and sources below"
                              : "Save this selection to inspect its matching vocabulary"
                          : "Select and save to inspect matching terms and source scope"}
                    </small>
                  </span>
                </label>
              ))}
              {visible.length === 0 && (
                <p>No catalogue entries match. Add a custom interest.</p>
              )}
            </div>
  </>;
}
