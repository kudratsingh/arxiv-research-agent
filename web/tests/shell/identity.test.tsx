/**
 * WO-W17b criteria 1 and 2, at the surface — what the identity slot renders.
 *
 * `tests/workspaceIdentity.test.ts` proves the descriptor is right. This file
 * proves the header says what the descriptor means, and it starts from the
 * claim that is easiest to break by accident:
 *
 *   CRITERION 1 IS A BYTE COMPARISON, NOT A "LOOKS THE SAME". `SHARED_SLOT_HTML`
 *   below is the markup this element produced on `5bcf373`, before any of this
 *   existed — copied out of the JSX that rendered it, not out of a run of the
 *   new code. If the descriptor plumbing changed one attribute, one space or
 *   one character of copy on a deployment with the pilot mode off, this file is
 *   red. That is what lets `tests/shell/shell.test.tsx`,
 *   `tests/copy/shell-copy.test.ts` and every existing story stay untouched and
 *   still mean what they meant.
 *
 *   CRITERION 2 IS ABOUT WHAT IS *NOT* IN THE DOM. Under pilot mode the slot
 *   names one person — the pilot's own username, which the browser's credential
 *   dialog already collected from them. Nothing else off the server may appear:
 *   not the API key it maps to, not the `key_id` that key lands on rows as, not
 *   the edge secret, and not which of a dozen faults refused a request. The
 *   assertions below scan the whole rendered document for each of them rather
 *   than checking the sentence, because the sentence is not where a leak would
 *   arrive — a `title`, a `data-` attribute or a debug prop is.
 *
 * D-009 IS RE-ASSERTED HERE, NOT ASSUMED. `IdentitySlot` still renders nothing
 * in all three states, and there is still no control anywhere in the header
 * whose name mentions signing in. A work order that put a username on screen is
 * exactly the one that could quietly grow an account menu beside it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LearnLayout from "@/app/(learn)/layout";
import WorkspaceLayout from "@/app/(workspace)/layout";
import { WorkbenchShell } from "@/components/app/WorkbenchShell";
import { WORKSPACE, WORKSPACE_PILOT } from "@/lib/copy/threads";
import type { WorkspaceIdentity } from "@/lib/identity";
import {
  PILOT_EDGE_SECRET_ENV,
  PILOT_MAP_ENV,
  PILOT_MODE_ENV,
} from "@/lib/server/pilot";

import { render, screen } from "../support/render";
import { MODE_WIDTHS, installMatchMedia, uninstallMatchMedia } from "./support";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/",
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

/**
 * The element as `5bcf373` rendered it, transcribed from that commit's JSX.
 *
 *     <p className="ew-shell__workspace">
 *       <strong className="font-medium text-ink">{WORKSPACE.indicator}</strong>{" "}
 *       {WORKSPACE.indicatorDetail}
 *     </p>
 */
const SHARED_SLOT_HTML =
  '<p class="ew-shell__workspace">' +
  '<strong class="font-medium text-ink">Shared workspace</strong>' +
  " Everyone with access to this deployment sees these threads." +
  " There are no separate accounts.</p>";

const EDGE_SECRET = "unit_suite_edge_secret_local_preview_00000";
const ADA_KEY_ID = "ada-key-id";
const ADA_API_KEY = "sk_ada_secret_local_preview";
const MAP = JSON.stringify({
  "pilot-ada": { key_id: ADA_KEY_ID, api_key: ADA_API_KEY },
});

beforeEach(() => {
  installMatchMedia({ width: MODE_WIDTHS.expanded });
});

afterEach(() => {
  uninstallMatchMedia();
});

/** The shell with a stand-in rail: no network, no data layer, no providers. */
function renderShell(identity?: WorkspaceIdentity) {
  return render(
    <WorkbenchShell rail={<div />} identity={identity}>
      <h1>A route</h1>
    </WorkbenchShell>,
  );
}

/** The identity slot's element. One per document, by construction. */
function slot(): HTMLElement {
  const found = document.querySelectorAll<HTMLElement>(".ew-shell__workspace");
  expect(found).toHaveLength(1);
  return found[0] as HTMLElement;
}

// ---------------------------------------------------------------------------
// Criterion 1.
// ---------------------------------------------------------------------------

describe("criterion 1 — with no pilot mode, the slot is what it was", () => {
  it("renders the pre-change markup byte for byte when the prop is omitted", () => {
    renderShell();
    expect(slot().outerHTML).toBe(SHARED_SLOT_HTML);
  });

  it("renders the same markup for an explicit `shared` descriptor", () => {
    renderShell({ kind: "shared" });
    expect(slot().outerHTML).toBe(SHARED_SLOT_HTML);
  });

  it("carries no `data-workspace-identity` hook, because a byte is a byte", () => {
    // The hook exists for the two states the e2e tier has to select. Adding it
    // to the shared state as well would have been tidier and would have broken
    // the comparison above, which is the one criterion 1 is stated as.
    renderShell();
    expect(slot().hasAttribute("data-workspace-identity")).toBe(false);
  });

  it("still composes §6's sentence out of the dictionary", () => {
    renderShell();
    expect(slot().textContent).toContain(WORKSPACE.indicator);
    expect(slot().textContent).toContain(WORKSPACE.indicatorDetail);
  });
});

// ---------------------------------------------------------------------------
// Criterion 2.
// ---------------------------------------------------------------------------

describe("criterion 2 — under pilot mode the slot names the pilot", () => {
  it("states the pilot workspace and who the edge authenticated", () => {
    renderShell({ kind: "pilot", username: "pilot-ada" });
    const text = slot().textContent ?? "";
    expect(text).toContain(WORKSPACE_PILOT.indicator);
    expect(text).toContain("pilot-ada");
    // The sentence that was false: it must be gone, not merely qualified.
    expect(text).not.toContain(WORKSPACE.indicatorDetail);
    expect(text).not.toContain("Shared workspace");
  });

  it("says what is per person and what is shared, because both are true", () => {
    renderShell({ kind: "pilot", username: "pilot-ada" });
    const text = (slot().textContent ?? "").toLowerCase();
    for (const perPerson of ["threads", "guided sessions", "learner profile", "ledger"]) {
      expect(text, perPerson).toContain(perPerson);
    }
    // `docs/runbooks/pilot.md` §8 tells each pilot the caches are shared. A
    // header claiming total separation would contradict their onboarding note.
    expect(text).toContain("paper and embedding caches are shared");
  });

  it("puts no key, key id, edge secret or fault anywhere in the document", () => {
    renderShell({ kind: "pilot", username: "pilot-ada" });
    const document_ = document.body.innerHTML;
    for (const secret of [ADA_API_KEY, ADA_KEY_ID, EDGE_SECRET, MAP]) {
      expect(document_, `${secret} reached the DOM`).not.toContain(secret);
    }
    for (const fault of [
      "untrusted_topology",
      "unknown_username",
      "shared_key_also_set",
      "map_unparseable",
    ]) {
      expect(document_, `${fault} reached the DOM`).not.toContain(fault);
    }
    for (const name of [PILOT_MODE_ENV, PILOT_MAP_ENV, PILOT_EDGE_SECRET_ENV]) {
      expect(document_, `${name} reached the DOM`).not.toContain(name);
    }
  });

  it("offers the hook the browser tier selects on", () => {
    renderShell({ kind: "pilot", username: "pilot-ada" });
    expect(slot().getAttribute("data-workspace-identity")).toBe("pilot");
  });
});

describe("criterion 2 — an unproven request says so, and names nobody", () => {
  it("states that no principal was resolved", () => {
    renderShell({ kind: "unresolved" });
    const text = slot().textContent ?? "";
    expect(text).toContain(WORKSPACE_PILOT.unresolvedIndicator);
    expect(text).toContain(WORKSPACE_PILOT.unresolvedDetail);
    expect(slot().getAttribute("data-workspace-identity")).toBe("unresolved");
  });

  it("never falls back to the shared sentence — that is the whole bug", () => {
    renderShell({ kind: "unresolved" });
    expect(slot().textContent).not.toContain("Shared workspace");
    expect(slot().textContent).not.toContain(WORKSPACE.indicatorDetail);
  });

  it("names no username and no fault", () => {
    renderShell({ kind: "unresolved" });
    const text = document.body.innerHTML;
    expect(text).not.toContain("pilot-ada");
    expect(text).not.toContain("untrusted_topology");
    // It points at the one person who can fix it instead.
    expect(slot().textContent).toMatch(/operator/i);
  });
});

// ---------------------------------------------------------------------------
// D-009, in all three states.
// ---------------------------------------------------------------------------

describe("D-009 — a username is not a login, in any state", () => {
  const STATES: [string, WorkspaceIdentity][] = [
    ["shared", { kind: "shared" }],
    ["pilot", { kind: "pilot", username: "pilot-ada" }],
    ["unresolved", { kind: "unresolved" }],
  ];

  it.each(STATES)("renders no account control under %s", (_label, identity) => {
    renderShell(identity);
    // `IdentitySlot` is still the empty reservation it was: no avatar, no
    // menu, no disabled button. 03 §6 — "a disabled login button is still a
    // fake login" — and nothing about knowing a username changes that.
    expect(document.querySelector("img")).toBeNull();
    const controls = [
      ...screen.queryAllByRole("button"),
      ...screen.queryAllByRole("link"),
    ];
    for (const control of controls) {
      expect(control.textContent ?? "").not.toMatch(/sign[- ]?in|sign[- ]?out|log[- ]?in/i);
      expect(control.getAttribute("aria-label") ?? "").not.toMatch(
        /sign[- ]?in|sign[- ]?out|log[- ]?in|account|profile/i,
      );
    }
  });

  it.each(STATES)("keeps exactly one main landmark under %s", (_label, identity) => {
    renderShell(identity);
    expect(document.querySelectorAll("main")).toHaveLength(1);
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// The two layouts, which are the only modules that resolve a descriptor.
// ---------------------------------------------------------------------------

describe("both group layouts derive the slot from the same seam", () => {
  const saved = {
    mode: process.env[PILOT_MODE_ENV],
    map: process.env[PILOT_MAP_ENV],
    secret: process.env[PILOT_EDGE_SECRET_ENV],
  };
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    // The rail is real in a layout — that is what `tests/shell/wiring.test.tsx`
    // is about — so it fetches. An empty list is enough here; this file is
    // about the header.
    globalThis.fetch = vi.fn(
      async () =>
        new Response("[]", {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    ) as unknown as typeof fetch;
    delete process.env[PILOT_MODE_ENV];
    delete process.env[PILOT_MAP_ENV];
    delete process.env[PILOT_EDGE_SECRET_ENV];
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    for (const [name, value] of [
      [PILOT_MODE_ENV, saved.mode],
      [PILOT_MAP_ENV, saved.map],
      [PILOT_EDGE_SECRET_ENV, saved.secret],
    ] as const) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  });

  /** Both layouts, driven the way an async server component has to be. */
  const LAYOUTS: [string, (children: React.ReactNode) => Promise<React.ReactElement>][] =
    [
      ["(workspace)", (children) => WorkspaceLayout({ children })],
      ["(learn)", (children) => LearnLayout({ children })],
    ];

  it.each(LAYOUTS)(
    "%s renders the shared slot, byte for byte, with the mode off",
    async (_label, layout) => {
      render(await layout(<h1>A route</h1>));
      expect(slot().outerHTML).toBe(SHARED_SLOT_HTML);
    },
  );

  it.each(LAYOUTS)(
    "%s renders `unresolved` under pilot mode when the request cannot be read",
    async (_label, layout) => {
      // A jsdom render has no request scope, so `next/headers` throws and the
      // deriver gets `null`. Under pilot mode that is not a shared deployment
      // and must not be rendered as one — the same refusal a spoofed header
      // gets, reached from the other direction.
      process.env[PILOT_MODE_ENV] = "on";
      process.env[PILOT_MAP_ENV] = MAP;
      process.env[PILOT_EDGE_SECRET_ENV] = EDGE_SECRET;

      render(await layout(<h1>A route</h1>));
      expect(slot().textContent).toContain(WORKSPACE_PILOT.unresolvedIndicator);
      expect(slot().outerHTML).not.toBe(SHARED_SLOT_HTML);
      expect(document.body.innerHTML).not.toContain(ADA_API_KEY);
    },
  );

  it.each(LAYOUTS)("%s never throws on a broken configuration", async (_label, layout) => {
    // A layout that threw would replace the page with an error boundary
    // because a sentence in the header could not be composed.
    process.env[PILOT_MODE_ENV] = "yes-please";
    process.env[PILOT_MAP_ENV] = "{not json";
    process.env[PILOT_EDGE_SECRET_ENV] = "x";

    render(await layout(<h1>A route</h1>));
    expect(slot().textContent).toContain(WORKSPACE_PILOT.unresolvedIndicator);
    expect(screen.getByRole("heading", { name: "A route" })).toBeInTheDocument();
  });
});
