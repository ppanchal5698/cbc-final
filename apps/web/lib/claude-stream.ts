/**
 * Turning the CLI's own event stream into terminal lines or structured log entries.
 *
 * `claude --print` on a pty writes only the final answer, so there is nothing to
 * watch during a run; `--output-format stream-json --verbose` makes it report
 * each tool call as it happens. That JSON is the real process output.
 */

const DIM = "\x1b[2m";
const RESET = "\x1b[0m";
const CYAN = "\x1b[36m";
const GREEN = "\x1b[32m";
const YELLOW = "\x1b[33m";
const RED = "\x1b[31m";
const BOLD = "\x1b[1m";

export interface StreamRender {
  /** Terminal-ready text, newline-terminated. */
  lines: string;
  /** Leftover bytes of a JSON line that has not fully arrived yet. */
  remainder: string;
}

export interface ParseResult {
  entries: LogEntry[];
  remainder: string;
}

interface ParseContext {
  sessionInits: number;
}

export type LogFilter =
  | "all"
  | "agent"
  | "tools"
  | "system"
  | "errors";

export interface BaseEntry {
  id: string;
  time: string;
}

export interface SessionEntry extends BaseEntry {
  kind: "session";
  model: string;
  toolCount: number;
  mcpServers: { name: string; status: string }[];
  sessionRole?: "orchestrator" | "subagent" | "retry";
  attempt?: number;
}

export interface WarningEntry extends BaseEntry {
  kind: "warning";
  message: string;
}

export interface ApiRetryEntry extends BaseEntry {
  kind: "api_retry";
  attempt: number;
  maxRetries: number;
  error: string;
}

export interface AgentTextEntry extends BaseEntry {
  kind: "agent_text";
  text: string;
}

export interface ToolCallEntry extends BaseEntry {
  kind: "tool_call";
  toolUseId: string;
  name: string;
  input: Record<string, unknown>;
  summary: string;
  result?: {
    body: string;
    isError: boolean;
    size: number;
  };
}

export interface ErrorEntry extends BaseEntry {
  kind: "error";
  message: string;
}

export interface DoneEntry extends BaseEntry {
  kind: "done";
  turns: number | string;
  seconds: string;
  costUsd: number | null;
  isError: boolean;
}

export interface RateLimitEntry extends BaseEntry {
  kind: "rate_limit";
  subtype: string;
}

export interface PlainEntry extends BaseEntry {
  kind: "plain";
  text: string;
}

export type LogEntry =
  | SessionEntry
  | WarningEntry
  | ApiRetryEntry
  | AgentTextEntry
  | ToolCallEntry
  | ErrorEntry
  | DoneEntry
  | RateLimitEntry
  | PlainEntry;

let entryCounter = 0;

function nextId(): string {
  entryCounter += 1;
  return `e-${entryCounter}`;
}

/** The API base64s the recording so escape sequences survive JSON intact. */
export function decodeBase64Recording(payload: string): string {
  try {
    const binary = atob(payload);
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  } catch {
    return payload;
  }
}

/**
 * The event's own timestamp, not the moment the browser parsed it.
 */
export function formatEventTime(event?: Record<string, unknown>): string {
  const stamp =
    (event?.timestamp as string | undefined) ??
    ((event?.message as Record<string, unknown> | undefined)?.timestamp as string | undefined);
  const when = stamp ? new Date(stamp) : new Date();
  if (Number.isNaN(when.getTime())) {
    return new Date().toLocaleTimeString([], { hour12: false });
  }
  return when.toLocaleTimeString([], { hour12: false });
}

function clock(event?: Record<string, unknown>): string {
  return `${DIM}${formatEventTime(event)}${RESET}`;
}

export function summariseInput(name: string, input: Record<string, unknown>): string {
  const interesting = [
    "file_path",
    "path",
    "query",
    "page_range",
    "pages",
    "part_number",
    "command",
    "project",
    "description",
    "namespace",
    "toolName",
  ];
  for (const key of interesting) {
    const value = input?.[key];
    if (typeof value === "string" && value) {
      const short = value.length > 60 ? `${value.slice(0, 57)}…` : value;
      return short.replace(/\s+/g, " ");
    }
    if (typeof value === "number") return String(value);
  }
  return "";
}

function summariseInputAnsi(name: string, input: Record<string, unknown>): string {
  const text = summariseInput(name, input);
  return text ? `${DIM}${text}${RESET}` : "";
}

function toolResultBody(content: unknown): string {
  return typeof content === "string" ? content : JSON.stringify(content ?? "");
}

function parseWarningLine(line: string): LogEntry | null {
  const match = line.match(/^\[claude-code:([^\]]+)\]\s*(.*)$/);
  if (!match) return null;
  const [, tag, rest] = match;
  let message = tag;
  if (rest?.trim()) {
    try {
      const payload = JSON.parse(rest) as Record<string, unknown>;
      message = `${tag}: ${JSON.stringify(payload)}`;
    } catch {
      message = `${tag}: ${rest.trim()}`;
    }
  }
  return {
    id: nextId(),
    kind: "warning",
    time: formatEventTime(),
    message,
  };
}

function parseEvent(
  event: Record<string, unknown>,
  ctx: { sessionInits: number },
): LogEntry[] {
  const time = formatEventTime(event);
  const out: LogEntry[] = [];

  switch (event.type) {
    case "system": {
      if (event.subtype === "init") {
        ctx.sessionInits += 1;
        const tools = Array.isArray(event.tools) ? event.tools.length : 0;
        const mcpServers = Array.isArray(event.mcp_servers)
          ? (event.mcp_servers as { name?: string; status?: string }[]).map((s) => ({
              name: s.name ?? "?",
              status: s.status ?? "?",
            }))
          : [];
        out.push({
          id: nextId(),
          kind: "session",
          time,
          model: String(event.model ?? "?"),
          toolCount: tools,
          mcpServers,
          sessionRole: ctx.sessionInits === 1 ? "orchestrator" : "subagent",
        });
      } else if (event.subtype === "error") {
        out.push({
          id: nextId(),
          kind: "error",
          time,
          message: String(event.message ?? "system error"),
        });
      } else if (event.subtype === "api_retry") {
        out.push({
          id: nextId(),
          kind: "api_retry",
          time,
          attempt: Number(event.attempt ?? 0),
          maxRetries: Number(event.max_retries ?? 0),
          error: String(event.error ?? "unknown"),
        });
      }
      break;
    }
    case "assistant": {
      const message = event.message as Record<string, unknown> | undefined;
      const content = (message?.content as Record<string, unknown>[] | undefined) ?? [];
      for (const block of content) {
        if (block.type === "tool_use") {
          const input = (block.input as Record<string, unknown>) ?? {};
          const name = String(block.name ?? "?");
          out.push({
            id: nextId(),
            kind: "tool_call",
            time,
            toolUseId: String(block.id ?? nextId()),
            name,
            input,
            summary: summariseInput(name, input),
          });
        } else if (block.type === "text" && typeof block.text === "string" && block.text.trim()) {
          out.push({
            id: nextId(),
            kind: "agent_text",
            time,
            text: block.text.trimEnd(),
          });
        }
      }
      if (event.error || event.is_api_error_message) {
        const textBlock = content.find((b) => b.type === "text" && b.text);
        out.push({
          id: nextId(),
          kind: "error",
          time,
          message: String(textBlock?.text ?? event.error ?? "assistant error"),
        });
      }
      break;
    }
    case "user": {
      const message = event.message as Record<string, unknown> | undefined;
      const content = (message?.content as Record<string, unknown>[] | undefined) ?? [];
      for (const block of content) {
        if (block.type !== "tool_result") continue;
        const body = toolResultBody(block.content);
        out.push({
          id: nextId(),
          kind: "tool_call",
          time,
          toolUseId: String(block.tool_use_id ?? nextId()),
          name: "(result)",
          input: {},
          summary: "",
          result: {
            body,
            isError: Boolean(block.is_error),
            size: body.length,
          },
        });
      }
      break;
    }
    case "result": {
      const seconds = event.duration_ms ? (Number(event.duration_ms) / 1000).toFixed(1) : "?";
      out.push({
        id: nextId(),
        kind: "done",
        time,
        turns: (event.num_turns as number | string | undefined) ?? "?",
        seconds,
        costUsd: event.total_cost_usd != null ? Number(event.total_cost_usd) : null,
        isError: Boolean(event.is_error),
      });
      break;
    }
    case "rate_limit_event": {
      out.push({
        id: nextId(),
        kind: "rate_limit",
        time,
        subtype: String(event.subtype ?? "rate limit"),
      });
      break;
    }
    default:
      break;
  }
  return out;
}

/** Pair tool results onto their matching tool_use rows. */
export function mergeEntries(existing: LogEntry[], incoming: LogEntry[]): LogEntry[] {
  const merged = [...existing];
  const callIndex = new Map<string, number>();

  for (let i = 0; i < merged.length; i += 1) {
    const entry = merged[i];
    if (entry.kind === "tool_call" && !entry.result) {
      callIndex.set(entry.toolUseId, i);
    }
  }

  for (const entry of incoming) {
    if (entry.kind === "tool_call" && entry.result) {
      const idx = callIndex.get(entry.toolUseId);
      if (idx != null) {
        const call = merged[idx];
        if (call.kind === "tool_call") {
          merged[idx] = {
            ...call,
            result: entry.result,
            time: entry.time,
          };
          continue;
        }
      }
    }
    if (entry.kind === "tool_call" && !entry.result) {
      callIndex.set(entry.toolUseId, merged.length);
    }
    merged.push(entry);
  }

  return merged;
}

/** Parse complete JSON lines into structured log entries. */
export function parseStream(
  chunk: string,
  carried = "",
  ctx: ParseContext = { sessionInits: 0 },
): ParseResult {
  const buffered = carried + chunk;
  const pieces = buffered.split("\n");
  const remainder = pieces.pop() ?? "";
  const entries: LogEntry[] = [];

  for (const piece of pieces) {
    const trimmed = piece.trim();
    if (!trimmed) continue;

    const retryMatch = trimmed.match(/^=== RETRY attempt (\d+) ===$/);
    if (retryMatch) {
      ctx.sessionInits = 0;
      entries.push({
        id: nextId(),
        kind: "session",
        time: formatEventTime(),
        model: "retry",
        toolCount: 0,
        mcpServers: [],
        sessionRole: "retry",
        attempt: Number(retryMatch[1]),
      });
      continue;
    }

    if (!trimmed.startsWith("{")) {
      const warning = parseWarningLine(trimmed);
      if (warning) {
        entries.push(warning);
      } else {
        entries.push({
          id: nextId(),
          kind: "plain",
          time: formatEventTime(),
          text: trimmed,
        });
      }
      continue;
    }

    try {
      entries.push(...parseEvent(JSON.parse(trimmed) as Record<string, unknown>, ctx));
    } catch {
      entries.push({
        id: nextId(),
        kind: "plain",
        time: formatEventTime(),
        text: trimmed.slice(0, 200),
      });
    }
  }

  return { entries, remainder };
}

export function entryMatchesFilter(entry: LogEntry, filter: LogFilter): boolean {
  if (filter === "all") return true;
  if (filter === "agent") {
    return entry.kind === "agent_text";
  }
  if (filter === "tools") {
    return entry.kind === "tool_call";
  }
  if (filter === "system") {
    return (
      entry.kind === "session" ||
      entry.kind === "warning" ||
      entry.kind === "api_retry" ||
      entry.kind === "rate_limit" ||
      entry.kind === "plain" ||
      entry.kind === "done"
    );
  }
  if (filter === "errors") {
    return (
      entry.kind === "error" ||
      entry.kind === "warning" ||
      (entry.kind === "tool_call" && Boolean(entry.result?.isError)) ||
      (entry.kind === "done" && entry.isError)
    );
  }
  return true;
}

export function countByFilter(entries: LogEntry[]): Record<LogFilter, number> {
  const filters: LogFilter[] = ["all", "agent", "tools", "system", "errors"];
  const counts = {} as Record<LogFilter, number>;
  for (const filter of filters) {
    counts[filter] =
      filter === "all"
        ? entries.length
        : entries.filter((entry) => entryMatchesFilter(entry, filter)).length;
  }
  return counts;
}

function copyPrefix(time: string): string {
  return `[${time}]`;
}

/** Plain-text serialization of one log entry for clipboard export. */
export function formatEntryForCopy(entry: LogEntry): string {
  switch (entry.kind) {
    case "session": {
      const servers = entry.mcpServers.map((s) => `${s.name}:${s.status}`).join(", ");
      const mcp = servers ? ` mcp=[${servers}]` : "";
      const role =
        entry.sessionRole === "retry"
          ? `RETRY attempt ${entry.attempt ?? "?"}`
          : entry.sessionRole === "subagent"
            ? "SUBAGENT SESSION"
            : entry.sessionRole === "orchestrator"
              ? "ORCHESTRATOR SESSION"
              : "SESSION";
      return `${copyPrefix(entry.time)} ${role} model=${entry.model} tools=${entry.toolCount}${mcp}`;
    }
    case "warning":
      return `${copyPrefix(entry.time)} WARNING ${entry.message}`;
    case "api_retry":
      return `${copyPrefix(entry.time)} API RETRY ${entry.attempt}/${entry.maxRetries}: ${entry.error}`;
    case "agent_text":
      return `${copyPrefix(entry.time)} AGENT\n${entry.text}`;
    case "tool_call": {
      let line = `${copyPrefix(entry.time)} CALL ${entry.name}`;
      if (entry.summary) line += ` ${entry.summary}`;
      line += `\n  Input: ${JSON.stringify(entry.input)}`;
      if (entry.result) {
        const status = entry.result.isError ? "FAILED" : "OK";
        line += `\n  Result (${status}, ${entry.result.size} chars):\n${entry.result.body}`;
      } else {
        line += "\n  Result: pending";
      }
      return line;
    }
    case "error":
      return `${copyPrefix(entry.time)} ERROR ${entry.message}`;
    case "done": {
      const cost = entry.costUsd != null ? ` $${entry.costUsd.toFixed(3)}` : "";
      const err = entry.isError ? " (error)" : "";
      return `${copyPrefix(entry.time)} DONE ${entry.turns} turns in ${entry.seconds}s${cost}${err}`;
    }
    case "rate_limit":
      return `${copyPrefix(entry.time)} RATE LIMIT ${entry.subtype}`;
    case "plain":
      return `${copyPrefix(entry.time)} ${entry.text}`;
    default:
      return "";
  }
}

/** Full run transcript as plain text (all entries, not filter-scoped). */
export function formatEntriesForCopy(entries: LogEntry[]): string {
  return entries.map(formatEntryForCopy).filter(Boolean).join("\n\n");
}

function renderEvent(event: Record<string, unknown>): string[] {
  const out: string[] = [];
  const at = clock(event);

  switch (event.type) {
    case "system": {
      if (event.subtype === "init") {
        const tools = Array.isArray(event.tools) ? event.tools.length : 0;
        const servers = Array.isArray(event.mcp_servers)
          ? (event.mcp_servers as { name?: string; status?: string }[])
              .map((s) => `${s.name}:${s.status}`)
              .join(" ")
          : "";
        out.push(
          `${at} ${BOLD}session${RESET} ${DIM}model${RESET} ${String(event.model ?? "?")} ${DIM}tools${RESET} ${tools}`,
        );
        if (servers) out.push(`${at} ${BOLD}mcp${RESET}     ${servers}`);
      } else if (event.subtype === "error") {
        out.push(`${at} ${RED}error${RESET}   ${String(event.message ?? "").slice(0, 200)}`);
      }
      break;
    }
    case "assistant": {
      const message = event.message as Record<string, unknown> | undefined;
      const content = (message?.content as Record<string, unknown>[] | undefined) ?? [];
      for (const block of content) {
        if (block.type === "tool_use") {
          const name = String(block.name ?? "?");
          const input = (block.input as Record<string, unknown>) ?? {};
          out.push(`${at} ${CYAN}call${RESET}    ${name} ${summariseInputAnsi(name, input)}`);
        } else if (block.type === "text" && typeof block.text === "string" && block.text.trim()) {
          for (const line of block.text.trimEnd().split("\n")) {
            out.push(`${at} ${DIM}·${RESET}       ${line}`);
          }
        }
      }
      break;
    }
    case "user": {
      const message = event.message as Record<string, unknown> | undefined;
      const content = (message?.content as Record<string, unknown>[] | undefined) ?? [];
      for (const block of content) {
        if (block.type !== "tool_result") continue;
        const body = toolResultBody(block.content);
        const size = body.length;
        const tone = block.is_error ? RED : GREEN;
        const label = block.is_error ? "failed" : "ok";
        out.push(
          `${at} ${tone}${label}${RESET}${block.is_error ? "  " : "      "}${DIM}${size.toLocaleString()} chars${RESET}`,
        );
        if (block.is_error) {
          out.push(`${at} ${RED}│${RESET}       ${body.slice(0, 300).replace(/\s+/g, " ")}`);
        }
      }
      break;
    }
    case "result": {
      const seconds = event.duration_ms ? (Number(event.duration_ms) / 1000).toFixed(1) : "?";
      const tone = event.is_error ? RED : GREEN;
      out.push(
        `${at} ${tone}${BOLD}done${RESET}    ${String(event.num_turns ?? "?")} turns in ${seconds}s` +
          (event.total_cost_usd
            ? ` ${DIM}$${Number(event.total_cost_usd).toFixed(3)}${RESET}`
            : ""),
      );
      break;
    }
    case "rate_limit_event": {
      out.push(`${at} ${YELLOW}limit${RESET}   ${String(event.subtype ?? "rate limit")}`);
      break;
    }
    default:
      break;
  }
  return out;
}

/** Render whatever complete JSON lines are present; keep the rest for next time. */
export function renderStream(chunk: string, carried = "", raw = false): StreamRender {
  const buffered = carried + chunk;
  const pieces = buffered.split("\n");
  const remainder = pieces.pop() ?? "";

  if (raw) return { lines: pieces.join("\r\n") + (pieces.length ? "\r\n" : ""), remainder };

  const rendered: string[] = [];
  for (const piece of pieces) {
    const trimmed = piece.trim();
    if (!trimmed) continue;
    if (!trimmed.startsWith("{")) {
      rendered.push(`${DIM}${trimmed}${RESET}`);
      continue;
    }
    try {
      rendered.push(...renderEvent(JSON.parse(trimmed) as Record<string, unknown>));
    } catch {
      rendered.push(`${DIM}${trimmed.slice(0, 200)}${RESET}`);
    }
  }
  return {
    lines: rendered.length ? rendered.join("\r\n") + "\r\n" : "",
    remainder,
  };
}
