"use client";

import { useEffect, useRef, useState } from "react";

import {
  decodeBase64Recording,
  mergeEntries,
  parseStream,
  renderStream,
  type LogEntry,
} from "@/lib/claude-stream";
import { endpoints } from "@/lib/endpoints";
import { proxyFetch } from "@/lib/proxy-fetcher";

export type RecordingState = "connecting" | "live" | "ended" | "unavailable";

interface TerminalReplay {
  available: boolean;
  reason?: string | null;
  data?: string | null;
  bytes?: number | null;
  status?: string | null;
}

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

export function useJobRecording(
  jobId: string,
  options?: {
    onFinished?: (status: string) => void;
    onRawChunk?: (lines: string) => void;
    parseEntries?: boolean;
  },
) {
  const { onFinished, onRawChunk, parseEntries = true } = options ?? {};
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [state, setState] = useState<RecordingState>("connecting");
  const [reason, setReason] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState(jobId);
  const carried = useRef("");
  const sessionCtx = useRef({ sessionInits: 0 });
  const rawCarried = useRef("");
  const offset = useRef(0);
  const seenEntryIds = useRef(new Set<string>());
  const endedRef = useRef(false);
  const rawLogRef = useRef("");

  // Callbacks are read through refs so that a caller passing an inline function
  // does not tear down and re-open the EventSource on every render.
  const onRawChunkRef = useRef(onRawChunk);
  const onFinishedRef = useRef(onFinished);
  useEffect(() => {
    onRawChunkRef.current = onRawChunk;
    onFinishedRef.current = onFinished;
  });

  // A new job clears the transcript before the subscription effect runs.
  if (activeJobId !== jobId) {
    setActiveJobId(jobId);
    setEntries([]);
    setState("connecting");
    setReason(null);
  }

  useEffect(() => {
    let disposed = false;
    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    carried.current = "";
    sessionCtx.current = { sessionInits: 0 };
    rawCarried.current = "";
    offset.current = 0;
    seenEntryIds.current = new Set();
    endedRef.current = false;
    rawLogRef.current = "";

    const appendRaw = (chunk: string) => {
      if (chunk) rawLogRef.current += chunk;
    };

    const appendEntries = (incoming: LogEntry[]) => {
      if (!incoming.length) return;
      setEntries((prev) => {
        const fresh = incoming.filter((entry) => {
          if (seenEntryIds.current.has(entry.id)) return false;
          seenEntryIds.current.add(entry.id);
          return true;
        });
        return fresh.length ? mergeEntries(prev, fresh) : prev;
      });
    };

    const openStream = () => {
      if (disposed) return;
      source?.close();
      source = new EventSource(
        `/api/proxy/jobs/${jobId}/terminal/stream?offset=${offset.current}`,
      );
      setState("live");

      source.addEventListener("output", (event) => {
        const chunk = decodeBase64Recording((event as MessageEvent).data);
        offset.current += byteLength(chunk);
        appendRaw(chunk);

        if (parseEntries) {
          const next = parseStream(chunk, carried.current, sessionCtx.current);
          carried.current = next.remainder;
          appendEntries(next.entries);
        }

        const rawNext = renderStream(chunk, rawCarried.current, true);
        rawCarried.current = rawNext.remainder;
        if (rawNext.lines) onRawChunkRef.current?.(rawNext.lines);
      });

      source.addEventListener("end", (event) => {
        endedRef.current = true;
        setState("ended");
        source?.close();
        onFinishedRef.current?.((event as MessageEvent).data);
      });

      source.onerror = () => {
        source?.close();
        if (disposed || endedRef.current) return;
        reconnectTimer = setTimeout(openStream, 1500);
      };
    };

    (async () => {
      let replay: TerminalReplay;
      try {
        const response = await proxyFetch(endpoints.jobTerminal(jobId));
        if (!response.ok) throw new Error(`the API answered ${response.status}`);
        replay = (await response.json()) as TerminalReplay;
      } catch (error) {
        // Without this the hook sat on "connecting" for ever and the rejection
        // went unhandled: a dead API looked identical to a slow one.
        if (disposed) return;
        setState("unavailable");
        setReason(
          `Could not load this run's recording — ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
        return;
      }
      if (disposed) return;

      if (!replay.available) {
        setState("unavailable");
        setReason(replay.reason ?? null);
        return;
      }

      if (replay.data) {
        const decoded = decodeBase64Recording(replay.data);
        appendRaw(decoded);
        if (parseEntries) {
          const first = parseStream(decoded, "", sessionCtx.current);
          carried.current = first.remainder;
          appendEntries(first.entries);
        }
        const rawFirst = renderStream(decoded, "", true);
        rawCarried.current = rawFirst.remainder;
        if (rawFirst.lines) onRawChunkRef.current?.(rawFirst.lines);
        offset.current = replay.bytes ?? byteLength(decoded);
      }

      if (replay.status && ["done", "failed", "cancelled"].includes(replay.status)) {
        endedRef.current = true;
        setState("ended");
        return;
      }

      openStream();
    })();

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      source?.close();
    };
  }, [jobId, parseEntries]);

  return {
    entries,
    state,
    reason,
    getRawLog: () => rawLogRef.current,
  };
}
