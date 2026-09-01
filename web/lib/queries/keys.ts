// Query and mutation keys — and the single definition of the principal
// segment that seam S5 reserves (04-ARCHITECTURE.md §10).
//
// **Every key is `[resource, principal, …]`.** `PRINCIPAL` is a module
// constant today because there is no user identity and D-009 forbids
// faking one. When MT-01 makes the principal session-derived, this file
// is the only edit site: caches partition automatically and no call site
// changes. That is the whole point of the seam — the position in the key
// is reserved now so partitioning later is not a re-architecture.
//
// Keys are built by factories rather than written inline so that
// `web/tests/queries/keys.test.ts` can walk the whole surface and prove
// the segment is never omitted. A key assembled by hand at a call site
// would be invisible to that walk, so there are none.

/**
 * The cache partition every key carries.
 *
 * `"shared"` is honest: one API key serves every browser that reaches
 * this deployment (`web/app/api/[...path]/route.ts:81-82`), so all
 * callers genuinely share one cache. It is not a placeholder user id and
 * must never be rendered — seam S6 forbids ownership copy.
 */
export const PRINCIPAL = "shared";

export type Principal = typeof PRINCIPAL;

/** The cache roots. Another root would need a seam review, not a string. */
export const QUERY_RESOURCES = [
  "conversations",
  "jobs",
  "learnPaths",
  "learnProgress",
] as const;

export type QueryResource = (typeof QUERY_RESOURCES)[number];

/**
 * Read keys.
 *
 * The `lists()` / `details()` entries are prefixes, not queries: they
 * exist so an invalidation or an optimistic write can address every page
 * of a list without knowing its page size.
 */
export const queryKeys = {
  conversations: {
    /** Everything under the conversations root, for one invalidation. */
    all: () => ["conversations", PRINCIPAL] as const,
    /** Prefix over every page size. */
    lists: () => ["conversations", PRINCIPAL, "list"] as const,
    /**
     * One paginated list. `limit` is in the key because it changes the
     * shape of a page; `offset` is not — it is the infinite query's page
     * param, and putting it in the key would give every page its own
     * cache entry and defeat "Load more".
     */
    list: (limit: number) => ["conversations", PRINCIPAL, "list", { limit }] as const,
    /** Prefix over every conversation detail. */
    details: () => ["conversations", PRINCIPAL, "detail"] as const,
    detail: (conversationId: string) =>
      ["conversations", PRINCIPAL, "detail", conversationId] as const,
  },
  jobs: {
    all: () => ["jobs", PRINCIPAL] as const,
    details: () => ["jobs", PRINCIPAL, "detail"] as const,
    detail: (jobId: string) => ["jobs", PRINCIPAL, "detail", jobId] as const,
  },
  learnPaths: {
    all: () => ["learnPaths", PRINCIPAL] as const,
    list: () => ["learnPaths", PRINCIPAL, "list"] as const,
    details: () => ["learnPaths", PRINCIPAL, "detail"] as const,
    detail: (pathId: string) =>
      ["learnPaths", PRINCIPAL, "detail", pathId] as const,
  },
  learnProgress: {
    all: () => ["learnProgress", PRINCIPAL] as const,
    summary: () => ["learnProgress", PRINCIPAL, "summary"] as const,
  },
} as const;

/**
 * Write keys.
 *
 * Three, and only three: the idempotent JSON writes 04-ARCHITECTURE.md
 * §4.1 assigns to `useMutation`. **`POST /research` is deliberately
 * absent** — it is not a mutation here, in `web/lib/queries/` at all, or
 * anywhere a library could replay it (H6, R-01). It belongs to the job
 * machine's plain guarded function. `web/tests/queries/research.test.ts`
 * asserts that absence rather than trusting it.
 */
export const mutationKeys = {
  conversations: {
    create: () => ["conversations", PRINCIPAL, "create"] as const,
    delete: () => ["conversations", PRINCIPAL, "delete"] as const,
  },
  jobs: {
    review: () => ["jobs", PRINCIPAL, "review"] as const,
  },
} as const;

/**
 * The shape both factories share, for the walk in the key test.
 *
 * Deliberately loose in its arguments: the test supplies a sample per
 * factory and asserts on the key that comes back, so the walk does not
 * need to know any factory's real parameter types.
 */
export type KeyFactoryTree = Readonly<
  Record<string, Readonly<Record<string, (...args: never[]) => readonly unknown[]>>>
>;

/** Both factories, so a test can walk everything that builds a key. */
export const KEY_FACTORIES: Readonly<Record<string, KeyFactoryTree>> = {
  queryKeys,
  mutationKeys,
};
