import { describe, expect, it, vi } from "vitest";

import LearnLayout from "@/app/(learn)/layout";
import LearnPage from "@/app/(learn)/learn/page";
import LearnPathPage from "@/app/(learn)/learn/paths/[id]/page";

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

describe("the learning route group", () => {
  it("shares the workbench shell and query boundary", () => {
    render(<LearnLayout><div data-testid="child" /></LearnLayout>);
    expect(screen.getByTestId("shell")).toBeVisible();
    expect(screen.getByTestId("rail")).toBeVisible();
    expect(screen.getByTestId("child")).toBeVisible();
  });

  it("composes the path-list route", () => {
    render(<LearnPage />);
    expect(screen.getByTestId("path-list")).toBeVisible();
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
});
