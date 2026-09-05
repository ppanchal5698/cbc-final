import { describe, expect, it } from "vitest";

import { formatEntriesForCopy, parseStream, type LogEntry } from "./claude-stream";

describe("formatEntriesForCopy", () => {
  it("serializes agent text and tool calls with full results", () => {
    const entries: LogEntry[] = [
      {
        id: "1",
        kind: "agent_text",
        time: "18:56:10",
        text: "Reading priced lines.",
      },
      {
        id: "2",
        kind: "tool_call",
        time: "18:56:12",
        toolUseId: "tu-1",
        name: "Read",
        input: { file_path: "/app/projects/test_bid/priced/line_items.json" },
        summary: "/app/projects/test_bid/priced/line_items.json",
        result: {
          body: '{"lines":[]}',
          isError: false,
          size: 12,
        },
      },
    ];

    const text = formatEntriesForCopy(entries);

    expect(text).toContain("[18:56:10] AGENT");
    expect(text).toContain("Reading priced lines.");
    expect(text).toContain("[18:56:12] CALL Read");
    expect(text).toContain('Input: {"file_path":"/app/projects/test_bid/priced/line_items.json"}');
    expect(text).toContain("Result (OK, 12 chars):");
    expect(text).toContain('{"lines":[]}');
  });

  it("joins multiple entries with blank lines", () => {
    const entries: LogEntry[] = [
      { id: "1", kind: "plain", time: "01:00:00", text: "first" },
      { id: "2", kind: "plain", time: "01:00:01", text: "second" },
    ];

    expect(formatEntriesForCopy(entries)).toBe(
      "[01:00:00] first\n\n[01:00:01] second",
    );
  });
});

describe("parseStream session labels", () => {
  it("labels the first init as orchestrator and later ones as subagent", () => {
    const ctx = { sessionInits: 0 };
    const init = JSON.stringify({
      type: "system",
      subtype: "init",
      model: "claude-sonnet",
      tools: ["Read"],
      mcp_servers: [],
    });

    const first = parseStream(`${init}\n`, "", ctx);
    const second = parseStream(`${init}\n`, "", ctx);

    expect(first.entries[0]).toMatchObject({
      kind: "session",
      sessionRole: "orchestrator",
    });
    expect(second.entries[0]).toMatchObject({
      kind: "session",
      sessionRole: "subagent",
    });
  });

  it("parses retry banners as retry sessions", () => {
    const parsed = parseStream("=== RETRY attempt 2 ===\n", "", { sessionInits: 1 });

    expect(parsed.entries[0]).toMatchObject({
      kind: "session",
      sessionRole: "retry",
      attempt: 2,
    });
  });
});
