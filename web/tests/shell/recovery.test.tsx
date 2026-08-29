/**
 * WO-09 — the recovery surfaces, asserted where they can be asserted
 * without a browser.
 *
 * The three claims that need one are evidenced in the PR body instead, per
 * the WO-01-c5 / WO-08 precedent: the axe `page-has-heading-one` run over
 * the built pages (criterion 2's second half), the Lighthouse CLS number
 * for the loading→loaded transition (criterion 4), and the visible reveal
 * of the skip link on `:focus-visible`, which jsdom cannot match. What is
 * here is everything that is structure rather than pixels — and structure
 * is what every one of the six criteria is actually about.
 *
 * ONE THING THIS FILE DELIBERATELY DOES NOT DO: reach for `axe-core`.
 * It is present in `node_modules` as a transitive dependency of
 * `@storybook/addon-a11y`, at the exact version the Gate 1 baseline used —
 * and importing it here would make the suite depend on a package
 * `package.json` does not declare. So `page-has-heading-one` is asserted in
 * its structural form (exactly one `h1`, with an accessible name, inside
 * the document), and the rule itself is run out-of-band against the built
 * pages with the baseline tag set.
 */

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GlobalError from "@/app/global-error";
import NotFoundPage from "@/app/not-found";
import WorkspaceError from "@/app/(workspace)/error";
import ThreadError from "@/app/(workspace)/c/[id]/error";
import ThreadLoading from "@/app/(workspace)/c/[id]/loading";
import { NotFound } from "@/components/patterns/NotFound";
import { GLOBAL_ERROR } from "@/lib/copy/globalError";
import { RECOVERY, ROUTE_ERROR } from "@/lib/copy/recovery";
import { MAIN_ID, RAIL_ID } from "@/components/app/WorkbenchShell";
import { THREAD, WORKSPACE } from "@/lib/copy/threads";

import { fireEvent, render, screen, user, within } from "../support/render";
import { MODE_WIDTHS, installMatchMedia, uninstallMatchMedia } from "./support";

const WEB_ROOT = path.resolve(__dirname, "..", "..");

const read = (file: string): string =>
  readFileSync(path.join(WEB_ROOT, file), "utf8");

/**
 * Comments stripped, because the criterion-5 assertions below are about
 * what the module *does*, and both of those files necessarily *discuss*
 * `var(--…)` and `.css` imports in the header that explains why they have
 * none. A check that a file never mentions a thing is not the same check as
 * one that it never uses it, and only the second is worth having.
 */
const readCode = (file: string): string =>
  read(file)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

// The same two stand-ins the rest of tests/shell/ uses: `next/link` needs an
// App Router context a bare render has no reason to build, and
// `ThreadRailBridge` reads the pathname.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/does-not-exist",
}));

const originalFetch = globalThis.fetch;

beforeEach(() => {
  installMatchMedia({ width: MODE_WIDTHS.expanded });
  // `app/not-found.tsx` renders the real rail, which is the only part of
  // the shell that fetches. An empty list is the honest answer for a 404.
  globalThis.fetch = vi.fn(
    async () =>
      new Response("[]", {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  ) as unknown as typeof fetch;
});

afterEach(() => {
  uninstallMatchMedia();
  globalThis.fetch = originalFetch;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Criterion 1 — the product 404, inside the shell.
// ---------------------------------------------------------------------------

describe("criterion 1 — app/not-found.tsx replaces the framework default", () => {
  it("renders inside the workbench shell, with the rail intact", () => {
    const { container } = render(<NotFoundPage />);

    // Exactly one `<main id="main">` — `landmark-one-main`, which fails in
    // 12 of 12 Gate 1 axe reports and which the framework 404 cannot pass
    // at all, because it renders no landmark of any kind.
    const mains = container.querySelectorAll("main");
    expect(mains).toHaveLength(1);
    expect(mains[0]?.id).toBe(MAIN_ID);

    // "the rail intact".
    const rail = screen.getByRole("navigation", { name: "Threads" });
    expect(rail).toBeInTheDocument();
    expect(rail.id).toBe(RAIL_ID);

    // And the shell's header, so the theme control and the workspace
    // indicator survive a 404 too.
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: WORKSPACE.skipToContent })).toBeInTheDocument();
  });

  it("puts a real h1 inside that main", () => {
    render(<NotFoundPage />);

    const main = screen.getByRole("main");
    const heading = within(main).getByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent(ROUTE_ERROR.notFoundHeading);
  });

  it("offers 'Start a new question' as the primary action, pointing at /", () => {
    render(<NotFoundPage />);

    const action = screen.getByRole("link", { name: ROUTE_ERROR.notFoundAction });
    expect(action).toHaveAttribute("href", "/");
    expect(ROUTE_ERROR.notFoundAction).toBe("Start a new question");
  });

  it("mounts the shell exactly once — the not-found boundary replaces the group layout", () => {
    // Next resolves an unmatched URL's boundary at the ROOT, so
    // `app/(workspace)/layout.tsx` does not render when this does. If it
    // ever did, there would be two shells and two `<main>` elements, which
    // is the failure this asserts against.
    const { container } = render(<NotFoundPage />);
    expect(container.querySelectorAll("[data-workbench-shell]")).toHaveLength(1);
    expect(container.querySelectorAll("header")).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Criterion 2 — every recovery surface renders an h1.
// ---------------------------------------------------------------------------

describe("criterion 2 — one h1, with a name, on every recovery surface", () => {
  const surfaces: Array<[string, ReactElement, string]> = [
    ["route 404", <NotFoundPage key="nf" />, ROUTE_ERROR.notFoundHeading],
    [
      "inline thread not-found",
      <NotFound
        key="inline"
        heading={THREAD.notFoundHeading}
        body={THREAD.notFoundBody}
        actionLabel={THREAD.notFoundBackToStart}
        actionHref="/"
        secondaryLabel={THREAD.notFoundBackToList}
        secondaryHref={`#${RAIL_ID}`}
      />,
      THREAD.notFoundHeading,
    ],
    [
      "workspace error boundary",
      <WorkspaceError key="we" error={new Error("boom")} reset={() => {}} />,
      ROUTE_ERROR.errorHeading,
    ],
    [
      "thread error boundary",
      <ThreadError key="te" error={new Error("boom")} reset={() => {}} />,
      RECOVERY.threadErrorHeading,
    ],
    ["route loading", <ThreadLoading key="tl" />, RECOVERY.loadingHeading],
  ];

  it.each(surfaces)("%s renders exactly one h1", async (_name, element, heading) => {
    const { container } = render(element);

    await screen.findByRole("heading", { level: 1, name: heading });
    const headings = container.querySelectorAll("h1");
    expect(headings).toHaveLength(1);
    // `page-has-heading-one` needs an h1; `empty-heading` needs it to have
    // an accessible name. The loading surface's is clipped, not absent.
    expect(headings[0]?.textContent?.trim()).toBe(heading);
  });

  it("the baseline state that failed the rule now passes its structural form", () => {
    // docs/revamp/baseline/axe/conversation-not-found.json is the single
    // `page-has-heading-one` violation in the whole Gate 1 set (03 §7.1).
    const { container } = render(
      <NotFound
        heading={THREAD.notFoundHeading}
        body={THREAD.notFoundBody}
        actionLabel={THREAD.notFoundBackToStart}
        actionHref="/"
      />,
    );
    expect(container.querySelectorAll("h1")).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Criterion 3 — the H8 sentence, as rendered.
// ---------------------------------------------------------------------------

describe("criterion 3 — the inline thread-not-found says both and claims neither", () => {
  it("names 'never existed' and 'another principal', and offers two routes out", () => {
    render(
      <NotFound
        heading={THREAD.notFoundHeading}
        body={THREAD.notFoundBody}
        actionLabel={THREAD.notFoundBackToStart}
        actionHref="/"
        secondaryLabel={THREAD.notFoundBackToList}
        secondaryHref={`#${RAIL_ID}`}
      />,
    );

    const body = screen.getByText(THREAD.notFoundBody);
    expect(body.textContent).toMatch(/never have existed/i);
    expect(body.textContent).toMatch(/another principal/i);
    expect(body.textContent).not.toMatch(/deleted/i);
    expect(body.textContent).not.toMatch(/no permission/i);

    expect(
      screen.getByRole("link", { name: THREAD.notFoundBackToStart }),
    ).toHaveAttribute("href", "/");
    expect(
      screen.getByRole("link", { name: THREAD.notFoundBackToList }),
    ).toHaveAttribute("href", `#${RAIL_ID}`);
  });

  it("renders one way out when the caller has only one", () => {
    render(
      <NotFound
        heading={ROUTE_ERROR.notFoundHeading}
        body={ROUTE_ERROR.notFoundBody}
        actionLabel={ROUTE_ERROR.notFoundAction}
        actionHref="/"
      />,
    );
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Criterion 4 — the loading state reserves the loaded geometry.
// ---------------------------------------------------------------------------

describe("criterion 4 — loading.tsx reserves the real header and report height", () => {
  it("holds open the header's two line boxes at the loaded line heights", () => {
    const { container } = render(<ThreadLoading />);

    const header = container.querySelector("header");
    expect(header).not.toBeNull();
    // The loaded header's own padding and rule (ConversationThread.tsx:189).
    expect(header?.className).toContain("px-6");
    expect(header?.className).toContain("py-4");
    expect(header?.className).toContain("border-b");

    const bars = header?.querySelectorAll<HTMLElement>(".ew-skeleton") ?? [];
    expect(bars).toHaveLength(2);
    // The title's line box, then the meta line's. Both are token line
    // heights rather than guessed pixels, so a type change moves the
    // reservation with the type.
    expect(bars[0]?.style.height).toBe("var(--text-ui-xl-line)");
    expect(bars[1]?.style.height).toBe("var(--text-ui-xs-line)");
  });

  it("gives the report column the remaining track rather than its own content height", () => {
    const { container } = render(<ThreadLoading />);

    const surface = container.querySelector('[data-recovery-surface="loading"]');
    expect(surface?.className).toContain("h-full");

    const report = container.querySelector(".min-h-0.flex-1");
    expect(report).not.toBeNull();
    expect(report?.className).toContain("overflow-hidden");
  });

  it("announces the load on the container, and hides the bars", () => {
    const { container } = render(<ThreadLoading />);

    expect(
      container.querySelector('[data-recovery-surface="loading"]')?.getAttribute("aria-busy"),
    ).toBe("true");
    for (const bar of container.querySelectorAll(".ew-skeleton")) {
      expect(bar.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("has no motion to lose under prefers-reduced-motion (03 §3.7)", () => {
    // The forbidden thing is skeleton shimmer, and the way to not have it
    // is to have no animation at all rather than to switch one off.
    const primitives = read("components/primitives/primitives.css");
    const rule = primitives.slice(primitives.indexOf(".ew-skeleton"));
    expect(rule.slice(0, rule.indexOf("}"))).not.toMatch(/animation|transition/);
  });

  it("replaced the ad-hoc string in every place it was rendered", () => {
    // Criterion 4 names `page.tsx:19`. Two other frames showed the same
    // string at the same wrong height, and a designed loading state that
    // only one of the three paths reaches is not a designed loading state.
    //
    // WO-31 DELETED THE THIRD. `components/ConversationThread.tsx` was one
    // of the three frames; the claim about it is now discharged by the file
    // not existing, which the assertion after this loop makes explicit.
    for (const file of [
      "app/(workspace)/c/[id]/page.tsx",
      "app/(workspace)/c/[id]/loading.tsx",
    ]) {
      const source = read(file);
      expect(source, file).toContain("<ThreadSkeleton />");
      // Comments still discuss the string they replaced; the code must not
      // render it.
      expect(readCode(file), file).not.toContain("Loading conversation");
    }

    // The third frame is gone rather than fixed (WO-31 criterion 1).
    expect(existsSync(path.join(WEB_ROOT, "components/ConversationThread.tsx"))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Criterion 5 — global-error survives with no shell and no tokens.
// ---------------------------------------------------------------------------

describe("criterion 5 — global-error.tsx renders without the shell or the token sheet", () => {
  const markup = renderToStaticMarkup(
    <GlobalError error={Object.assign(new Error("boom"), { digest: "abc123" })} reset={() => {}} />,
  );

  it("renders its own document, because it replaces the root layout", () => {
    expect(markup).toContain('<html lang="en">');
    expect(markup).toContain("<body>");
    expect(markup).toContain(GLOBAL_ERROR.documentTitle);
  });

  it("renders no shell: no workbench frame, no banner, no rail", () => {
    expect(markup).not.toContain("data-workbench-shell");
    expect(markup).not.toContain("<header");
    expect(markup).not.toContain("<nav");
    expect(markup).not.toContain("ew-shell");
  });

  it("still renders exactly one <main>, because a document owes one", () => {
    // Not the shell's — its own. Without it this is the only surface in the
    // product that fails `landmark-one-main` and `region`, which is the
    // pair 03 §7.1 exists to close. Measured in headless Chrome: one
    // `landmark-one-main` violation and four `region` violations before,
    // zero after.
    expect(markup.match(/<main/g) ?? []).toHaveLength(1);
  });

  it("uses no low-contrast system colour", () => {
    // `GrayText` is the user agent's DISABLED colour and is allowed to be
    // low-contrast by definition; axe scores it as a serious
    // `color-contrast` violation on this surface.
    expect(readCode("components/patterns/GlobalErrorSurface.tsx")).not.toContain("GrayText");
  });

  it("carries the h1 and the reload control", () => {
    expect(markup).toContain("<h1");
    expect(markup).toContain(GLOBAL_ERROR.heading);
    expect(markup).toContain(GLOBAL_ERROR.action);
  });

  it("shows the digest as labelled evidence, never as the message", () => {
    expect(markup).toContain("abc123");
    expect(markup).toContain(GLOBAL_ERROR.referenceLabel);
    // The sentence is still ours (RC-16): the digest is beside it, not
    // instead of it.
    expect(markup.indexOf(GLOBAL_ERROR.body)).toBeLessThan(markup.indexOf("abc123"));
  });

  it("omits the reference row entirely when the runtime produced no digest", () => {
    const noDigest = renderToStaticMarkup(
      <GlobalError error={new Error("boom")} reset={() => {}} />,
    );
    expect(noDigest).not.toContain(GLOBAL_ERROR.referenceLabel);
  });

  const tokenFree = [
    "app/global-error.tsx",
    "components/patterns/GlobalErrorSurface.tsx",
  ];

  it.each(tokenFree)("%s imports no stylesheet", (file) => {
    // A `.css` import is the only way a token could reach this surface, and
    // the surface is reached precisely when stylesheets may not have
    // loaded.
    expect(readCode(file)).not.toMatch(/\.css["']/);
  });

  it.each(tokenFree)("%s reads no custom property", (file) => {
    expect(readCode(file)).not.toMatch(/var\(--/);
  });

  it.each(tokenFree)("%s imports no module that would drag a stylesheet in", (file) => {
    // Every primitive and every other pattern imports
    // components/primitives/primitives.css, whose every colour is a
    // `var(--color-*)`. One of those imports here would undo the whole
    // argument silently.
    const imports = Array.from(
      readCode(file).matchAll(/from\s+["']([^"']+)["']/g),
      (match) => match[1] as string,
    );
    for (const specifier of imports) {
      expect(
        specifier.startsWith("@/components/primitives/"),
        `${file} imports ${specifier}`,
      ).toBe(false);
    }
  });

  it("its one control reloads the document rather than calling reset()", () => {
    // `reset()` re-renders the tree that just threw — here, the root layout.
    // If the failure was the stylesheet or the font manifest, that cannot
    // help and a fresh request can, so this boundary is the one place in
    // the product where the recovery is a reload. The copy says so
    // (GLOBAL_ERROR.action) and this asserts the control agrees.
    const reload = vi.fn();
    vi.stubGlobal("location", { reload });
    const reset = vi.fn();

    const { container } = render(<GlobalError error={new Error("boom")} reset={reset} />);
    const action = container.querySelector("button");
    expect(action?.textContent).toBe(GLOBAL_ERROR.action);

    fireEvent.click(action as HTMLButtonElement);

    expect(reload).toHaveBeenCalledTimes(1);
    expect(reset).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("renders no className at all, so no Tailwind utility can smuggle one in", () => {
    // Every colour, space and type utility in this design system resolves
    // to a `var(--…)`, so "no class" is the enforceable form of "no token".
    expect(markup).not.toContain("class=");
  });

  it("styles itself with CSS system colours, which need no stylesheet", () => {
    const source = readCode("components/patterns/GlobalErrorSurface.tsx");
    expect(source).toContain("Canvas");
    expect(source).toContain("CanvasText");
    // `color-scheme` is what makes those follow the OS preference with no
    // pre-paint script and no `data-theme`.
    expect(source).toContain("colorScheme");
  });
});

// ---------------------------------------------------------------------------
// The boundaries' controls.
// ---------------------------------------------------------------------------

describe("the error boundaries re-render, and send nothing", () => {
  it("the workspace boundary calls reset and nothing else", async () => {
    const reset = vi.fn();
    render(<WorkspaceError error={new Error("boom")} reset={reset} />);

    await user().click(
      await screen.findByRole("button", { name: ROUTE_ERROR.errorAction }),
    );

    expect(reset).toHaveBeenCalledTimes(1);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("the thread boundary calls reset and nothing else", async () => {
    const reset = vi.fn();
    render(<ThreadError error={new Error("boom")} reset={reset} />);

    await user().click(
      await screen.findByRole("button", { name: ROUTE_ERROR.errorAction }),
    );

    expect(reset).toHaveBeenCalledTimes(1);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("shows the digest when there is one, and no row when there is not", async () => {
    const { unmount } = render(
      <ThreadError
        error={Object.assign(new Error("boom"), { digest: "3f1c9ad0" })}
        reset={() => {}}
      />,
    );
    expect(await screen.findByText("3f1c9ad0")).toBeInTheDocument();
    expect(screen.getByText(RECOVERY.referenceLabel)).toBeInTheDocument();
    unmount();

    render(<ThreadError error={new Error("boom")} reset={() => {}} />);
    await screen.findByRole("heading", { level: 1, name: RECOVERY.threadErrorHeading });
    expect(screen.queryByText(RECOVERY.referenceLabel)).toBeNull();
  });

  it("is not a live region: 03 §7.3 allows two product-wide and both are taken", async () => {
    const { container } = render(<WorkspaceError error={new Error("boom")} reset={() => {}} />);
    await screen.findByRole("heading", { level: 1, name: ROUTE_ERROR.errorHeading });
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('[role="status"]')).toBeNull();
  });
});
