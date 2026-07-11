import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import EventLog from "@/components/EventLog";
import type { SseEvent } from "@/lib/types";

function makeEvent(
  name: SseEvent["name"],
  data: SseEvent["data"] = null
): SseEvent {
  return { name, data, receivedAt: 1_700_000_000_000 };
}

describe("EventLog", () => {
  it("renders each event as a row with name + detail", () => {
    const events: SseEvent[] = [
      makeEvent("job_started", { job_id: "abc" }),
      makeEvent("node_completed", {
        node: "planner",
        state_delta: { iteration: 0 },
      }),
      makeEvent("job_completed", { elapsed_sec: 42.7 }),
    ];
    render(<EventLog events={events} />);
    expect(screen.getByText("job_started")).toBeInTheDocument();
    expect(screen.getByText("node_completed")).toBeInTheDocument();
    expect(screen.getByText("job_completed")).toBeInTheDocument();
  });

  it("formats node_completed with node + state_delta", () => {
    const events: SseEvent[] = [
      makeEvent("node_completed", {
        node: "critic",
        state_delta: { iteration: 1, quality_score: 0.9 },
      }),
    ];
    render(<EventLog events={events} />);
    expect(
      screen.getByText(/node=critic iteration=1 quality_score=0\.90/)
    ).toBeInTheDocument();
  });

  it("formats job_failed with error type + message", () => {
    render(
      <EventLog
        events={[
          makeEvent("job_failed", {
            error_type: "RuntimeError",
            error: "workflow blew up",
          }),
        ]}
      />
    );
    expect(
      screen.getByText(/RuntimeError: workflow blew up/)
    ).toBeInTheDocument();
  });

  it("formats job_completed elapsed as one decimal", () => {
    render(
      <EventLog events={[makeEvent("job_completed", { elapsed_sec: 3.4567 })]} />
    );
    expect(screen.getByText(/elapsed=3\.5s/)).toBeInTheDocument();
  });

  it("is accessible as a live log", () => {
    render(<EventLog events={[makeEvent("job_started")]} />);
    const log = screen.getByRole("log");
    expect(log).toHaveAttribute("aria-live", "polite");
  });

  it("renders empty list when no events", () => {
    render(<EventLog events={[]} />);
    const log = screen.getByRole("log");
    expect(log).toBeEmptyDOMElement();
  });
});
