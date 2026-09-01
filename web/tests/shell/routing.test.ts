/**
 * WO-08 criterion 2 — `(workspace)` introduces no URL segment.
 *
 * "`/` and `/c/[id]?job=` are byte-identical, asserted by a routing test."
 * The honest way to assert that without a build is to apply the App
 * Router's own rule to the filesystem: a directory wrapped in parentheses
 * is a *route group* and contributes nothing to the pathname
 * (04-ARCHITECTURE.md §2.1). So this file derives the route set from the
 * files on disk and asserts it equals the route set that existed before the
 * move — not that the files are where somebody expected them to be.
 *
 * The `?job=` half of the criterion is a search parameter, which no layout
 * or route group can touch; what could break it is the page forgetting to
 * read it. That is asserted here too, against the page's source, because it
 * is MUST-KEEP #1 (ADR 0053) and a silent regression costs a paid job.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const WEB_ROOT = path.resolve(__dirname, "..", "..");
const APP_ROOT = path.join(WEB_ROOT, "app");

/** Route files the App Router treats as a page. */
const PAGE_FILE = /^page\.(tsx|ts|jsx|js)$/;

interface PageFile {
  /** Path relative to `app/`, POSIX separators. */
  file: string;
  /** The URL the App Router serves it at. */
  route: string;
}

function collectPages(dir: string, relative = ""): PageFile[] {
  const found: PageFile[] = [];
  for (const entry of readdirSync(dir).sort()) {
    const absolute = path.join(dir, entry);
    if (statSync(absolute).isDirectory()) {
      found.push(...collectPages(absolute, relative ? `${relative}/${entry}` : entry));
      continue;
    }
    if (!PAGE_FILE.test(entry)) continue;
    const segments = relative
      .split("/")
      .filter(Boolean)
      // THE RULE: a parenthesised segment is a route group and contributes
      // no URL segment. Private folders (`_name`) contribute none either.
      .filter((segment) => !(segment.startsWith("(") && segment.endsWith(")")))
      .filter((segment) => !segment.startsWith("_"));
    found.push({
      file: relative ? `${relative}/${entry}` : entry,
      route: `/${segments.join("/")}`,
    });
  }
  return found;
}

describe("criterion 2 — the route group adds no URL segment", () => {
  const pages = collectPages(APP_ROOT);

  it("keeps the workspace routes and adds the two parenthesis-free learning URLs", () => {
    expect(pages.map((page) => page.route).sort()).toEqual([
      "/",
      "/c/[id]",
      "/learn",
      "/learn/paths/[id]",
    ]);
  });

  it("serves them from inside the (workspace) group", () => {
    const byRoute = Object.fromEntries(pages.map((page) => [page.route, page.file]));
    expect(byRoute["/"]).toBe("(workspace)/page.tsx");
    expect(byRoute["/c/[id]"]).toBe("(workspace)/c/[id]/page.tsx");
  });

  it("leaves no page file outside a shell-owning route group", () => {
    // A page at `app/page.tsx` would render without the layout — which is
    // exactly how the missing `<main>` arrived in the first place
    // (04 §2.1: "both wrap manually today").
    for (const page of pages) {
      expect(
        page.file.startsWith("(workspace)/") || page.file.startsWith("(learn)/"),
        `${page.file} is outside a shell-owning group`,
      ).toBe(true);
    }
  });

  it("shares WorkbenchShell from both group layouts", () => {
    for (const group of ["(workspace)", "(learn)"]) {
      const layout = readFileSync(path.join(APP_ROOT, group, "layout.tsx"), "utf8");
      expect(layout, group).toContain("WorkbenchShell");
    }
  });

  it("puts the shell in the group's layout, not in the pages", () => {
    const layout = readFileSync(path.join(APP_ROOT, "(workspace)", "layout.tsx"), "utf8");
    expect(layout).toContain("WorkbenchShell");

    for (const page of pages) {
      const source = readFileSync(path.join(APP_ROOT, page.file), "utf8");
      // The import, not the word: both files carry a comment explaining
      // that the wrapper is gone, and a substring match would read that
      // comment as the thing it documents.
      expect(source, `${page.file} still imports the old shell`).not.toMatch(
        /^import .*ConversationsShell/m,
      );
      expect(source, `${page.file} still renders the old shell`).not.toMatch(
        /<ConversationsShell/,
      );
    }
  });
});

describe("criterion 2 — the `?job=` contract survives the move (ADR 0053)", () => {
  it("the landing page still hands the accepted job_id to /c/[id]", () => {
    // WO-20 MOVED THE EXPRESSION, NOT THE CONTRACT. The three lines that
    // composed this URL by hand at `page.tsx:37-40` are now
    // `LandingComposer.handoffHref`, which is the only place the route can
    // reach it: the page mounts that component and nothing else. So the
    // string is asserted where it now lives, and the page is asserted to be
    // wired to it — two checks instead of one, because the hand-off crossing
    // a file boundary is exactly when a source-text assertion stops being
    // enough on its own.
    const page = readFileSync(path.join(APP_ROOT, "(workspace)", "page.tsx"), "utf8");
    expect(page).toContain("LandingComposer");

    const composer = readFileSync(
      path.join(WEB_ROOT, "components", "features", "LandingComposer.tsx"),
      "utf8",
    );
    expect(composer).toContain("?job=${encodeURIComponent(jobId)}");
  });

  it("the conversation page still reads it back out of the URL", () => {
    const source = readFileSync(
      path.join(APP_ROOT, "(workspace)", "c", "[id]", "page.tsx"),
      "utf8",
    );
    expect(source).toContain('searchParams.get("job")');
    expect(source).toContain("adoptJobId=");
  });
});
