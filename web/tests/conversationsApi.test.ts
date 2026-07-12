import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  ApiError,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  submitResearch,
} from "@/lib/api";

const originalFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("createConversation", () => {
  it("POSTs without a body when no title is given", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResp(
        {
          conversation_id: "c1",
          title: "New conversation",
          created_at: 0,
          updated_at: 0,
          jobs: [],
        },
        201
      )
    );
    const got = await createConversation();
    expect(got.conversation_id).toBe("c1");
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(call?.[1]?.method).toBe("POST");
    expect(JSON.parse(call?.[1]?.body as string)).toEqual({});
  });

  it("POSTs the title when provided", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResp(
        {
          conversation_id: "c1",
          title: "My topic",
          created_at: 0,
          updated_at: 0,
          jobs: [],
        },
        201
      )
    );
    await createConversation("My topic");
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(JSON.parse(call?.[1]?.body as string)).toEqual({ title: "My topic" });
  });
});

describe("listConversations", () => {
  it("fetches and returns the list", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResp([
        {
          conversation_id: "c1",
          title: "T",
          created_at: 0,
          updated_at: 0,
        },
      ])
    );
    const got = await listConversations();
    expect(got.length).toBe(1);
    expect(got[0]?.conversation_id).toBe("c1");
  });
});

describe("getConversation", () => {
  it("URL-encodes the conversation_id path segment", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResp({
        conversation_id: "a b",
        title: "T",
        created_at: 0,
        updated_at: 0,
        jobs: [],
      })
    );
    await getConversation("a b");
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(call?.[0]).toContain("/conversations/a%20b");
  });

  it("throws ApiError on 404", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResp({ detail: "conversation_not_found" }, 404)
    );
    try {
      await getConversation("nope");
      throw new Error("expected getConversation to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(404);
    }
  });
});

describe("deleteConversation", () => {
  it("issues a DELETE", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(null, { status: 204 })
    );
    await deleteConversation("c1");
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(call?.[1]?.method).toBe("DELETE");
    expect(call?.[0]).toContain("/conversations/c1");
  });
});

describe("submitResearch with conversation_id", () => {
  it("passes conversation_id in the request body", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResp(
        {
          job_id: "j",
          status: "pending",
          status_url: "/research/j",
          stream_url: "/research/j/stream",
        },
        202
      )
    );
    await submitResearch("hallucination", { conversation_id: "c1" });
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(JSON.parse(call?.[1]?.body as string)).toEqual({
      query: "hallucination",
      conversation_id: "c1",
    });
  });

  it("omits conversation_id when not provided", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResp(
        {
          job_id: "j",
          status: "pending",
          status_url: "/research/j",
          stream_url: "/research/j/stream",
        },
        202
      )
    );
    await submitResearch("q");
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    const body = JSON.parse(call?.[1]?.body as string);
    expect(body).toEqual({ query: "q" });
  });
});
