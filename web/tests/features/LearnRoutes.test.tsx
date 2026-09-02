import { describe, expect, it, vi } from "vitest";

import LearnLayout from "@/app/(learn)/layout";
import LearnPage from "@/app/(learn)/learn/page";
import LearnPathPage from "@/app/(learn)/learn/paths/[id]/page";
import LearnProgressPage from "@/app/(learn)/learn/progress/page";
import LearnSessionPage from "@/app/(learn)/learn/sessions/[id]/page";

import { render, screen } from "../support/render";

vi.mock("@/components/app/ThreadRailBridge", () => ({
  default: () => <nav data-testid="rail" />,
}));

vi.mock("@/components/app/WorkbenchShell", () => ({
  WorkbenchShell: ({ children, rail }: React.PropsWithChildren<{ rail: React.ReactNode }>) => (
    <div data-testid="shell">
      {rail}
      {children}
    </div>
  ),
}));

vi.mock("@/app/providers", () => ({
  QueryProvider: ({ children }: React.PropsWithChildren) => <>{children}</>,
}));

vi.mock("@/components/features/PathListSurface", () => ({
  PathListSurface: () => <div data-testid="path-list" />,
}));

vi.mock("@/components/features/PathDetailSurface", () => ({
  PathDetailSurface: ({ pathId }: { pathId: string }) => (
    <div data-testid="path-detail" data-path-id={pathId} />
  ),
}));

vi.mock("@/components/features/SessionDetailSurface", () => ({
  SessionDetailSurface: ({ sessionId }: { sessionId: string }) => (
    <div data-testid="session-detail" data-session-id={sessionId} />
  ),
}));

vi.mock("@/components/features/LedgerSurface", () => ({
  LedgerSurface: () => <div data-testid="ledger" />,
}));

describe("the learning route group", () => {
  it("shares the workbench shell and query boundary", async () => {
    // `await LearnLayout(...)`: WO-W17b made both group layouts async server
    // components so they can resolve the request's identity descriptor, and
    // `createRoot` cannot render one. Same form the async root layout is
    // already driven with in `tests/fonts.test.ts`.
    render(await LearnLayout({ children: <div data-testid="child" /> }));
    expect(screen.getByTestId("shell")).toBeVisible();
    expect(screen.getByTestId("rail")).toBeVisible();
    expect(screen.getByTestId("child")).toBeVisible();
  });

  it("composes the path-list route", () => {
    render(<LearnPage />);
    expect(screen.getByTestId("path-list")).toBeVisible();
  });

  it("composes the Ledger route inside the same shell and query boundary", () => {
    render(<LearnProgressPage />);
    expect(screen.getByTestId("ledger")).toBeVisible();
  });

  it("passes the decoded dynamic segment to the path surface", async () => {
    const page = await LearnPathPage({
      params: Promise.resolve({ id: "fixture-guided-read" }),
    });
    render(page);
    expect(screen.getByTestId("path-detail")).toHaveAttribute(
      "data-path-id",
      "fixture-guided-read"
    );
  });

  it("passes the decoded dynamic segment to the session surface", async () => {
    // Next has already decoded the segment, so the surface receives the raw
    // session id and the client re-encodes it on the way out — which is why
    // `getLearnSession` owns the `encodeURIComponent` and this route does not.
    const page = await LearnSessionPage({
      params: Promise.resolve({ id: "baseline guided/session" }),
    });
    render(page);
    expect(screen.getByTestId("session-detail")).toHaveAttribute(
      "data-session-id",
      "baseline guided/session"
    );
  });
});
