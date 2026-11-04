import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Layout from "@/app/(live)/layout";
import { Coverage } from "@/components/workspace/Common";
import { WorkspaceShell } from "@/components/workspace/Shell";
import { workspace } from "./fixtures";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspace/today",
  notFound: () => { throw new Error("not found"); },
}));
afterEach(() => { vi.unstubAllEnvs(); });

function view() {
  vi.stubEnv("WORKSPACE_LIVE", "1");
  return render(Layout({ children: <WorkspaceShell><Coverage sources={workspace().sources} /></WorkspaceShell> }));
}

describe("server-configured workspace provenance", () => {
  it("defaults to real metadata wording when the preview flag is absent", () => {
    vi.stubEnv("WORKSPACE_SYNTHETIC_PREVIEW", "");
    view();
    expect(screen.getByText("Real source metadata · private server saves · generation off")).toBeInTheDocument();
    expect(screen.getByText(/A partial check contains real metadata/)).toBeInTheDocument();
    expect(screen.queryByText("Design preview · synthetic sample papers")).not.toBeInTheDocument();
  });
  it("labels the seeded design preview and its source coverage as synthetic", () => {
    vi.stubEnv("WORKSPACE_SYNTHETIC_PREVIEW", "1");
    view();
    expect(screen.getByText("Design preview · synthetic sample papers")).toBeVisible();
    expect(screen.getByText("Sample source checks · private server saves · generation off")).toBeVisible();
    expect(screen.getByText(/These sample papers and source check results are synthetic/)).toBeInTheDocument();
    expect(screen.getAllByText(/Synthetic sample status/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/A partial check contains real metadata/)).not.toBeInTheDocument();
    expect(screen.queryByText("Real source metadata · private server saves · generation off")).not.toBeInTheDocument();
  });
  it("requires the exact opt-in rather than treating any flag value as enabled", () => {
    vi.stubEnv("WORKSPACE_SYNTHETIC_PREVIEW", "true");
    view();
    expect(screen.getByText("Real source metadata · private server saves · generation off")).toBeInTheDocument();
  });
});
