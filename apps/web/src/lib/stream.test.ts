import { afterEach, describe, expect, it, vi } from "vitest";
import { parseSseBlock, streamChat } from "./api";

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("server-sent events", () => {
  it("parses one event block", () => {
    expect(parseSseBlock('event: delta\ndata: {"text":"Hi"}')).toEqual({
      event: "delta",
      data: { text: "Hi" },
    });
    expect(parseSseBlock("event: ping")).toBeNull();
  });

  it("streams stages and provisional text, then resolves with the final answer", async () => {
    const final = {
      answer: "Thirty days.",
      citations: [],
      insufficient_context: false,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: stage\ndata: {"stage":"retrieving"}\n\n',
          'event: delta\ndata: {"text":"Thir',
          'ty"}\n\nevent: delta\ndata: {"text":" days."}\n\n',
          `event: final\ndata: ${JSON.stringify(final)}\n\n`,
        ]),
      ),
    );
    const stages: string[] = [];
    let text = "";
    const result = await streamChat(
      { question: "How long?" },
      { onStage: (s) => stages.push(s), onDelta: (d) => (text += d) },
    );
    expect(stages).toEqual(["retrieving"]);
    expect(text).toBe("Thirty days.");
    expect(result).toEqual(final);
  });

  it("raises the safe error message from an error event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: error\ndata: {"code":"x","message":"Local AI is unavailable."}\n\n',
        ]),
      ),
    );
    await expect(streamChat({}, {})).rejects.toThrow(
      "Local AI is unavailable.",
    );
  });

  it("fails if the stream ends without a final answer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => sseResponse(['event: delta\ndata: {"text":"x"}\n\n'])),
    );
    await expect(streamChat({}, {})).rejects.toThrow("ended unexpectedly");
  });
});
