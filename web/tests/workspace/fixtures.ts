import type { WorkspaceState, WorkItem } from "@/lib/workspace/api";

export const SOURCE_TEXT =
  "A controlled retrieval study compares fixed baselines. The abstract does not describe all methods.";
export function work(overrides: Partial<WorkItem> = {}): WorkItem {
  return {
    work_id: "arxiv:2610.00001",
    version_id: "arxiv:2610.00001:v2",
    source_id: "arxiv-cs-lg",
    source_record_id: "2610.00001v2",
    title: "A controlled retrieval study",
    url: "https://arxiv.org/abs/2610.00001v2",
    authors: ["Example Researcher"],
    abstract: SOURCE_TEXT,
    access_state: "abstract",
    categories: ["cs.LG"],
    published_at: "2026-10-30T10:00:00Z",
    updated_at: "2026-11-02T10:00:00Z",
    published_precision: "second",
    updated_precision: "second",
    first_seen_at: "2026-11-02T15:00:00Z",
    fetched_at: "2026-11-02T15:00:00Z",
    content_hash: "digest-2",
    version_label: "v2",
    kind: "paper",
    versions: [
      {
        version_id: "arxiv:2610.00001:v1",
        version_label: "v1",
        abstract: "An earlier retrieval abstract.",
        access_state: "abstract",
        content_hash: "digest-1",
        fetched_at: "2026-10-30T15:00:00Z",
        source_scope: "abstract",
        title: "An earlier controlled retrieval study",
        url: "https://arxiv.org/abs/2610.00001v1",
        authors: ["Example Researcher"],
      },
      {
        version_id: "arxiv:2610.00001:v2",
        version_label: "v2",
        abstract: SOURCE_TEXT,
        access_state: "abstract",
        content_hash: "digest-2",
        fetched_at: "2026-11-02T15:00:00Z",
        source_scope: "abstract",
        title: "A controlled retrieval study",
        url: "https://arxiv.org/abs/2610.00001v2",
        authors: ["Example Researcher"],
      },
    ],
    reading: {
      revision: 0,
      status: "unread",
      anchor: "abstract:0",
      version_id: "",
      snoozed_until: null,
    },
    entries: [],
    reasons: ["Watch term: retrieval"],
    ...overrides,
  };
}
export function workspace(
  overrides: Partial<WorkspaceState> = {},
): WorkspaceState {
  const item = work();
  return {
    principal_key_id: "owner-a",
    profile: {
      revision: 1,
      data: {
        topics: ["ml:retrieval-and-memory"],
        custom_topics: ["retrieval"],
        exclusions: [],
        streams: ["core"],
        minutes: 15,
        research_question:
          "Can I evaluate retrieval within a fixed compute budget?",
        exploration: 0.15,
      },
    },
    works: [item],
    sources: [
      {
        source_id: "arxiv-cs-lg",
        name: "arXiv cs.LG",
        status: "ok",
        last_success_at: "2026-11-02T15:00:00Z",
        receipt: { request_count: 1, item_count: 1, limitation: "bounded" },
      },
      {
        source_id: "hf-blog",
        name: "Hugging Face Blog",
        status: "failed",
        last_success_at: null,
        receipt: { error: "timeout" },
      },
    ],
    editions: [
      {
        id: "edition-a",
        created_at: "2026-11-02T15:00:00Z",
        profile_revision: 1,
        minutes: 15,
        work_ids: [item.work_id],
        work_versions: {},
        coverage: [],
        status: "ready_partial",
      },
    ],
    schedule: {
      revision: 0,
      enabled: false,
      timezone: "America/Los_Angeles",
      local_time: "07:00",
      next_check: null,
    },
    tasks: [],
    generation: "approval_required",
    as_of: "2026-11-02T15:00:00Z",
    ...overrides,
  };
}
