import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import Layout from "@/app/(daily)/layout";
import Template from "@/app/(daily)/template";
import TodayPage from "@/app/(daily)/today/page";
import InterestsPage from "@/app/(daily)/interests/page";
import LibraryPage from "@/app/(daily)/library/page";
import ItemPage from "@/app/(daily)/library/items/[id]/page";
import dictionary from "@/lib/daily/topics.json";
import { readFileSync } from "node:fs";
import path from "node:path";

vi.mock("next/navigation", () => ({usePathname: () => "/today", notFound: () => { throw new Error("not found"); }}));
beforeEach(() => vi.unstubAllEnvs());
it("keeps the fictional preview off unless explicitly selected", () => {
  vi.stubEnv("WORKSPACE_PREVIEW", "");
  expect(() => Layout({children: "preview"})).toThrow("not found");
  vi.stubEnv("WORKSPACE_PREVIEW", "1");
  expect(Layout({children: "preview"})).toBe("preview");
});
it("mounts the daily shell around Today without replacing the research route", () => {
  render(<Template><TodayPage /></Template>);
  expect(screen.getByRole("link", {name: "Research a question"})).toHaveAttribute("href", "/");
  expect(screen.getByRole("main")).toContainElement(screen.getByRole("heading", {level: 1}));
});
it("refuses an unknown source instead of manufacturing a record", async () => {
  await expect(ItemPage({params: Promise.resolve({id: "missing"})})).rejects.toThrow("not found");
  const view = await ItemPage({params: Promise.resolve({id: "corpus-shift"})});
  render(view);
  expect(screen.getByRole("heading", {name: "Source abstract"})).toBeInTheDocument();
});
it("renders interests and library from the same routes used in the walkthrough", () => {
  const interests = render(<InterestsPage />); expect(screen.getByRole("searchbox")).toBeInTheDocument(); interests.unmount();
  render(<LibraryPage />); expect(screen.getByRole("heading", {name: "Keep the useful parts."})).toBeInTheDocument();
});
it("derives the full topic dictionary from the supplied seed without inventing mappings", () => {
  const seed = JSON.parse(readFileSync(path.resolve(__dirname, "../../../planning/11-daily-research-workspace/07-topic-seed.json"), "utf8"));
  expect(dictionary.topics).toEqual(seed.nodes.map((node: {id: string; label: string; kind: string; parent_ids: string[]}) => ({id:node.id,label:node.label,kind:node.kind,parents:node.parent_ids})));
  expect(dictionary.topics).toHaveLength(384);
});
