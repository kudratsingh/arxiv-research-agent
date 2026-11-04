import { createContext, useContext } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ControlBar, SidebarSection, StageHeaderSlot, WorkspaceSlots } from "@/components/workspace/Slots";

const ExampleContext = createContext("missing context");
function ContextValue() {
  return <span>{useContext(ExampleContext)}</span>;
}
function SlotContents() {
  return <>
    <SidebarSection label="Reading queue"><span>Sidebar content</span><ContextValue /></SidebarSection>
    <StageHeaderSlot><span>Header content</span><ContextValue /></StageHeaderSlot>
    <ControlBar><span>Bar content</span><ContextValue /></ControlBar>
  </>;
}

describe("workspace slots", () => {
  it("renders all content once inline without a provider", () => {
    const { container } = render(<div data-testid="inline"><SlotContents /></div>);
    const inline = within(screen.getByTestId("inline"));
    expect(inline.getByRole("region", { name: "Reading queue" })).toHaveTextContent("Sidebar content");
    for (const text of ["Sidebar content", "Header content", "Bar content"]) {
      expect(inline.getAllByText(text)).toHaveLength(1);
    }
    expect(container.querySelectorAll("[data-testid=inline]")).toHaveLength(1);
  });

  it("renders no fallback while provider targets are null, then portals once into each target", () => {
    const sidebar = document.createElement("aside");
    const header = document.createElement("header");
    const bar = document.createElement("div");
    document.body.append(sidebar, header, bar);
    try {
      const { rerender } = render(
        <ExampleContext.Provider value="context carried">
          <WorkspaceSlots sidebar={null} header={null} bar={null}><SlotContents /></WorkspaceSlots>
        </ExampleContext.Provider>,
      );
      for (const text of ["Sidebar content", "Header content", "Bar content"]) expect(screen.queryByText(text)).not.toBeInTheDocument();
      rerender(
        <ExampleContext.Provider value="context carried">
          <WorkspaceSlots sidebar={sidebar} header={header} bar={bar}><SlotContents /></WorkspaceSlots>
        </ExampleContext.Provider>,
      );
      for (const [target, text] of [[sidebar, "Sidebar content"], [header, "Header content"], [bar, "Bar content"]] as const) {
        expect(within(target).getByText(text)).toBeInTheDocument();
        expect(screen.getAllByText(text)).toHaveLength(1);
        expect(within(target).getByText("context carried")).toBeInTheDocument();
      }
    } finally {
      sidebar.remove(); header.remove(); bar.remove();
    }
  });

  it("preserves native form ownership for a portaled submit button", () => {
    const bar = document.createElement("div");
    document.body.append(bar);
    const onSubmit = vi.fn((event: React.FormEvent<HTMLFormElement>) => event.preventDefault());
    try {
      render(<WorkspaceSlots sidebar={null} header={null} bar={bar}>
        <form id="slot-test-form" onSubmit={onSubmit}><label>Question<input name="question" /></label></form>
        <ControlBar><button type="submit" form="slot-test-form">Save preferences</button></ControlBar>
      </WorkspaceSlots>);
      const button = within(bar).getByRole("button", { name: "Save preferences" }) as HTMLButtonElement;
      expect(button.closest("form")).toBeNull();
      expect(button.form).toBe(document.getElementById("slot-test-form"));
      fireEvent.click(button);
      expect(onSubmit).toHaveBeenCalledTimes(1);
    } finally {
      bar.remove();
    }
  });
});
