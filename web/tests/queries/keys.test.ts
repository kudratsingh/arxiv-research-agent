// WO-11 criterion 1 — every query key carries the principal segment
// (04-ARCHITECTURE.md §10, seam S5).
//
// The claim is about *every* key, so this file proves it two ways:
//
//   1. It walks the exported factories and asserts the shape of each key
//      that comes back. A factory with no registered sample argument
//      fails the walk, so a new key cannot be added without being
//      checked.
//   2. It scans `lib/queries/` for `queryKey:` / `mutationKey:` and
//      asserts each one is built by a factory. A key assembled inline at
//      a call site would satisfy (1) by being invisible to it; (2) is
//      what closes that hole.

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  KEY_FACTORIES,
  PRINCIPAL,
  QUERY_RESOURCES,
  mutationKeys,
  queryKeys,
} from "@/lib/queries/keys";

const QUERIES_DIR = join(process.cwd(), "lib", "queries");

/**
 * A representative argument list per factory, keyed by its dotted path.
 *
 * The walk below fails on a factory that is missing from this table AND
 * on a stale entry that no longer names a factory, so the table cannot
 * silently drift away from the code it exercises.
 */
const SAMPLES: Record<string, unknown[]> = {
  "queryKeys.conversations.all": [],
  "queryKeys.conversations.lists": [],
  "queryKeys.conversations.list": [50],
  "queryKeys.conversations.details": [],
  "queryKeys.conversations.detail": ["baseline-populated"],
  "queryKeys.jobs.all": [],
  "queryKeys.jobs.details": [],
  "queryKeys.jobs.detail": ["baseline-running"],
  "mutationKeys.conversations.create": [],
  "mutationKeys.conversations.delete": [],
  "mutationKeys.jobs.review": [],
};

interface WalkedKey {
  path: string;
  key: readonly unknown[];
}

function walkFactories(): WalkedKey[] {
  const walked: WalkedKey[] = [];
  for (const [factoryName, tree] of Object.entries(KEY_FACTORIES)) {
    for (const [resource, group] of Object.entries(tree)) {
      for (const [name, build] of Object.entries(group)) {
        const path = `${factoryName}.${resource}.${name}`;
        const args = SAMPLES[path];
        if (args === undefined) {
          throw new Error(
            `No sample arguments registered for ${path}. Add one to SAMPLES ` +
              `so the principal-segment walk covers it.`
          );
        }
        walked.push({
          path,
          key: (build as (...args: unknown[]) => readonly unknown[])(...args),
        });
      }
    }
  }
  return walked;
}

describe("the principal segment (S5)", () => {
  it("is the module constant the seam reserves, and nothing user-visible", () => {
    expect(PRINCIPAL).toBe("shared");
  });

  it("finds every factory the two trees expose", () => {
    const walked = walkFactories().map((entry) => entry.path).sort();
    expect(walked).toEqual(Object.keys(SAMPLES).sort());
    expect(walked.length).toBeGreaterThan(0);
  });

  it("is present in EVERY key, at index 1, with no exceptions", () => {
    const offenders = walkFactories().filter(
      (entry) => entry.key[1] !== PRINCIPAL
    );
    expect(offenders).toEqual([]);
  });

  it("follows a resource segment at index 0", () => {
    for (const { path, key } of walkFactories()) {
      expect(
        QUERY_RESOURCES.includes(key[0] as (typeof QUERY_RESOURCES)[number]),
        `${path} → ${JSON.stringify(key)}`
      ).toBe(true);
      expect(key.length).toBeGreaterThanOrEqual(2);
    }
  });

  it("partitions: two keys differ once the principal differs", () => {
    // The proof that MT-01 needs no call-site change. Same resource, same
    // id, different principal — different cache entry.
    const shared = queryKeys.conversations.detail("c1");
    const otherPrincipal = ["conversations", "someone-else", "detail", "c1"];
    expect(shared).not.toEqual(otherPrincipal);
    expect(shared[1]).toBe(PRINCIPAL);
  });

  it("keeps list pages in one cache entry, keyed by page size only", () => {
    // `offset` is the infinite query's page param. In the key it would
    // give every page its own entry and "Load more" would have nothing
    // to append to.
    expect(queryKeys.conversations.list(50)).toEqual([
      "conversations",
      PRINCIPAL,
      "list",
      { limit: 50 },
    ]);
    expect(queryKeys.conversations.list(50)).not.toEqual(
      queryKeys.conversations.list(25)
    );
  });

  it("makes the prefixes real prefixes, so one invalidation reaches a page", () => {
    const prefix = queryKeys.conversations.lists();
    const page = queryKeys.conversations.list(50);
    expect(page.slice(0, prefix.length)).toEqual([...prefix]);

    const root = queryKeys.conversations.all();
    expect(page.slice(0, root.length)).toEqual([...root]);
    expect(
      queryKeys.conversations.detail("c1").slice(0, root.length)
    ).toEqual([...root]);
  });
});

describe("no key is built outside the factories", () => {
  function queryLayerSources(): string[] {
    return readdirSync(QUERIES_DIR).filter((name) => name.endsWith(".ts"));
  }

  it("routes every queryKey/mutationKey through queryKeys or mutationKeys", () => {
    const offenders: string[] = [];
    for (const file of queryLayerSources()) {
      const source = readFileSync(join(QUERIES_DIR, file), "utf8");
      for (const line of source.split("\n")) {
        if (!/^\s*(queryKey|mutationKey):/.test(line)) continue;
        if (!/\b(queryKeys|mutationKeys)\./.test(line)) {
          offenders.push(`${file}: ${line.trim()}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("scans files that really exist", () => {
    expect(queryLayerSources().sort()).toEqual([
      "client.ts",
      "conversations.ts",
      "job.ts",
      "keys.ts",
    ]);
  });
});

describe("the mutation key surface", () => {
  it("is exactly the three idempotent writes §4.1 allows", () => {
    expect(Object.keys(mutationKeys.conversations).sort()).toEqual([
      "create",
      "delete",
    ]);
    expect(Object.keys(mutationKeys.jobs)).toEqual(["review"]);
  });
});
