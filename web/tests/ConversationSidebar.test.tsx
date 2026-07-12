import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConversationSidebar from "@/components/ConversationSidebar";

const originalFetch = globalThis.fetch;
const originalConfirm = globalThis.confirm;

beforeEach(() => {
  globalThis.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.confirm = originalConfirm;
});

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function mockList(items: unknown[]): void {
  (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
    jsonResp(items)
  );
}

// Renders in "next/link" — the mocked component just renders an anchor.
vi.mock("next/link", async () => {
  return {
    default: ({
      href,
      children,
      onClick,
      className,
      title,
    }: {
      href: string;
      children: React.ReactNode;
      onClick?: () => void;
      className?: string;
      title?: string;
    }) => (
      <a href={href} onClick={onClick} className={className} title={title}>
        {children}
      </a>
    ),
  };
});

describe("ConversationSidebar", () => {
  it("shows a New conversation button", async () => {
    mockList([]);
    render(
      <ConversationSidebar activeConversationId={null} onNavigate={vi.fn()} />
    );
    expect(
      screen.getByRole("button", { name: /new conversation/i })
    ).toBeInTheDocument();
  });

  it("shows an empty-state message when there are no conversations", async () => {
    mockList([]);
    render(
      <ConversationSidebar activeConversationId={null} onNavigate={vi.fn()} />
    );
    expect(
      await screen.findByText(/no conversations yet/i)
    ).toBeInTheDocument();
  });

  it("lists conversations with links to their /c/[id] URLs", async () => {
    mockList([
      {
        conversation_id: "c1",
        title: "Hallucination survey",
        created_at: 0,
        updated_at: 1,
      },
      {
        conversation_id: "c2",
        title: "RAG comparisons",
        created_at: 0,
        updated_at: 2,
      },
    ]);
    render(
      <ConversationSidebar activeConversationId={null} onNavigate={vi.fn()} />
    );
    const first = await screen.findByRole("link", {
      name: /hallucination survey/i,
    });
    expect(first).toHaveAttribute("href", "/c/c1");
    expect(
      screen.getByRole("link", { name: /rag comparisons/i })
    ).toHaveAttribute("href", "/c/c2");
  });

  it("highlights the active conversation", async () => {
    mockList([
      {
        conversation_id: "c1",
        title: "Active thread",
        created_at: 0,
        updated_at: 1,
      },
    ]);
    render(
      <ConversationSidebar
        activeConversationId="c1"
        onNavigate={vi.fn()}
      />
    );
    const link = await screen.findByRole("link", { name: /active thread/i });
    // Highlight class carries the accent color.
    expect(link.className).toMatch(/bg-blue-100|bg-blue-950/);
  });

  it("creates a new conversation and navigates to it", async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResp([])) // initial list
      .mockResolvedValueOnce(
        jsonResp(
          {
            conversation_id: "c-new",
            title: "New conversation",
            created_at: 0,
            updated_at: 0,
            jobs: [],
          },
          201
        )
      ) // POST /conversations
      .mockResolvedValueOnce(jsonResp([])); // re-list after create

    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(
      <ConversationSidebar
        activeConversationId={null}
        onNavigate={onNavigate}
      />
    );
    await user.click(
      screen.getByRole("button", { name: /new conversation/i })
    );
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith("c-new"));
  });

  it("deletes a conversation on confirm and re-lists", async () => {
    globalThis.confirm = vi.fn(() => true);
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(
        jsonResp([
          {
            conversation_id: "c1",
            title: "T1",
            created_at: 0,
            updated_at: 0,
          },
        ])
      ) // initial list
      .mockResolvedValueOnce(
        new Response(null, { status: 204 })
      ) // DELETE
      .mockResolvedValueOnce(jsonResp([])); // re-list

    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(
      <ConversationSidebar
        activeConversationId="c1"
        onNavigate={onNavigate}
      />
    );
    const del = await screen.findByRole("button", { name: /delete t1/i });
    await user.click(del);
    // After deletion, empty-state renders; sidebar navigates home.
    await waitFor(() =>
      expect(screen.getByText(/no conversations yet/i)).toBeInTheDocument()
    );
    expect(onNavigate).toHaveBeenCalledWith("");
  });

  it("skips delete when confirm returns false", async () => {
    globalThis.confirm = vi.fn(() => false);
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResp([
        {
          conversation_id: "c1",
          title: "T1",
          created_at: 0,
          updated_at: 0,
        },
      ])
    );

    const user = userEvent.setup();
    render(
      <ConversationSidebar
        activeConversationId={null}
        onNavigate={vi.fn()}
      />
    );
    const del = await screen.findByRole("button", { name: /delete t1/i });
    await user.click(del);
    // Only the initial list should have fired; no DELETE.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
