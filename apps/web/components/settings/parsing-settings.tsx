"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { CheckCircle, Lock, Warning } from "@phosphor-icons/react/dist/ssr";

import type { ParsingSettings, ParsingTestResult } from "@/lib/types";
import { endpoints } from "@/lib/endpoints";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { cn } from "@/lib/utils";

const INT_FIELDS = [
  "windowPages",
  "windowConcurrency",
  "windowTimeoutSeconds",
  "waitMaxSeconds",
] as const;

const FIELD_META: Record<string, { label: string; hint?: string; placeholder?: string }> = {
  apiKey: {
    label: "API key",
    hint: "Empty turns parsing off — extraction reads PDFs directly through pdf-tools. Stored server-side; never shown back.",
    placeholder: "llx-…",
  },
  tier: {
    label: "Tier",
    hint: "cost_effective and above return word, line and cell bounding boxes. `fast` does not, so a priced line would have no rectangle to point at on the sheet.",
  },
  lang: { label: "Language", placeholder: "en" },
  windowPages: {
    label: "Pages per window",
    hint: "How many pages go in one parse request (1–200). The document is uploaded once and every window reuses it.",
  },
  windowConcurrency: {
    label: "Windows at a time",
    hint: "How many windows are parsed in parallel (1–16). A window is almost entirely spent waiting on the API, so this is the biggest lever on how long a bid set takes — 87 pages went from ~32 minutes to under a minute at 4. Too high and the API rate-limits instead of finishing.",
  },
  windowTimeoutSeconds: {
    label: "Window timeout (seconds)",
    hint: "60–7200. How long one window may take.",
  },
  waitMaxSeconds: {
    label: "Extraction wait max (seconds)",
    hint: "60–7200. How long extract jobs wait for parsing before proceeding.",
  },
};

const ENV_NAMES: Record<string, string> = {
  apiKey: "PARSER_API_KEY",
  tier: "PARSER_TIER",
  lang: "PARSER_LANG",
  windowPages: "PARSER_WINDOW_PAGES",
  windowConcurrency: "PARSER_WINDOW_CONCURRENCY",
  windowTimeoutSeconds: "PARSER_WINDOW_TIMEOUT_SECONDS",
  waitMaxSeconds: "PARSER_WAIT_MAX_SECONDS",
};

const ORDER = [
  "apiKey",
  "tier",
  "lang",
  "windowPages",
  "windowConcurrency",
  "windowTimeoutSeconds",
  "waitMaxSeconds",
];

type Draft = Record<string, string | number | null>;

function draftFromSettings(data: ParsingSettings): Draft {
  const draft: Draft = {};
  for (const key of ORDER) {
    const field = data.fields?.[key];
    // The API key comes back as "set" or "" — never the value, so an untouched
    // form must not post that placeholder back over a real key.
    draft[key] = key === "apiKey" ? "" : ((field?.value ?? "") as string | number);
  }
  return draft;
}

export function ParsingSettingsClient() {
  const { data, error, mutate, isLoading } = useSWR<ParsingSettings>(
    endpoints.parsingSettings(),
    proxyFetcher,
  );
  const [edits, setEdits] = useState<{ key: string; values: Draft } | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ParsingTestResult | null>(null);

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (error) return <p className="text-sm text-destructive">{errorMessage(error)}</p>;
  if (!data) return null;

  const stamp = `${data.updatedAt ?? ""}`;
  const draft = edits?.key === stamp ? edits.values : draftFromSettings(data);

  function set(key: string, value: string | number | null) {
    setEdits({ key: stamp, values: { ...draft, [key]: value } });
  }

  function payload() {
    const body: Record<string, unknown> = {};
    for (const key of ORDER) {
      const value = draft[key];
      if (key === "apiKey" && !String(value ?? "").trim()) continue; // unchanged
      if (value === "" || value === null) continue;
      body[key] = (INT_FIELDS as readonly string[]).includes(key) ? Number(value) : value;
    }
    return body;
  }

  async function save() {
    setSaving(true);
    try {
      await proxyMutate(endpoints.parsingSettings(), { method: "PUT", body: payload() });
      toast.success("Parsing settings saved");
      setEdits(null);
      await mutate();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function test() {
    setTesting(true);
    setResult(null);
    try {
      const body = await proxyMutate<ParsingTestResult>(endpoints.parsingSettingsTest(), {
        method: "POST",
        body: payload(),
      });
      setResult(body);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div
        className={cn(
          "flex items-center gap-2 rounded-md border px-3 py-2 text-sm",
          data.enabled ? "border-emerald-700/40 text-emerald-400" : "border-amber-700/40 text-amber-400",
        )}
      >
        {data.enabled ? <CheckCircle weight="bold" /> : <Warning weight="bold" />}
        <span>
          {data.enabled
            ? "Parsing is on. Uploaded bid PDFs are parsed into page blocks."
            : "Parsing is off. No API key, so extraction reads PDFs directly through pdf-tools."}
        </span>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {ORDER.map((key) => {
          const field = data.fields?.[key];
          const meta = FIELD_META[key] ?? { label: key };
          const locked = Boolean(field?.locked);
          const isInt = (INT_FIELDS as readonly string[]).includes(key);
          const isKeySet = key === "apiKey" && field?.value === "set";
          return (
            <label key={key} className="space-y-1 text-sm">
              <span className="flex items-center gap-1.5 font-medium">
                {meta.label}
                {locked && <Lock weight="bold" className="size-3.5 text-muted-foreground" />}
              </span>
              {key === "tier" ? (
                <select
                  className="w-full rounded-md border bg-background px-2 py-1.5"
                  value={String(draft[key] ?? "")}
                  disabled={locked}
                  onChange={(e) => set(key, e.target.value)}
                >
                  {(data.tiers ?? []).map((tier) => (
                    <option key={tier} value={tier}>
                      {tier}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className="w-full rounded-md border bg-background px-2 py-1.5"
                  type={key === "apiKey" ? "password" : isInt ? "number" : "text"}
                  value={String(draft[key] ?? "")}
                  placeholder={isKeySet ? "•••••••• (saved — type to replace)" : meta.placeholder}
                  disabled={locked}
                  onChange={(e) => set(key, e.target.value)}
                />
              )}
              <span className="block text-xs text-muted-foreground">
                {meta.hint}
                {locked && ` Set by ${ENV_NAMES[key]} in the environment.`}
              </span>
            </label>
          );
        })}
      </div>

      <div className="flex items-center gap-3">
        <button
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-60"
          onClick={save}
          disabled={saving}
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-60"
          onClick={test}
          disabled={testing}
        >
          {testing ? "Testing…" : "Test connection"}
        </button>
        <span className="text-xs text-muted-foreground">
          Test parses a generated one-page PDF against what is on screen, not what is saved.
        </span>
      </div>

      {result && (
        <div
          className={cn(
            "space-y-1 rounded-md border px-3 py-2 text-sm",
            result.ok ? "border-emerald-700/40 text-emerald-400" : "border-destructive/40 text-destructive",
          )}
        >
          <p>
            {result.ok
              ? `Parsed ${result.blocks ?? 0} block(s) in ${result.seconds ?? "?"}s on ${result.tier}.`
              : result.error}
          </p>
          {result.ok && result.verified != null && (
            <p className="text-xs">
              {Math.round(result.verified * 100)}% of the returned boxes sit on text that is
              really on the page. A low number here means the coordinate frame is wrong, and
              highlights would land away from their rows.
            </p>
          )}
        </div>
      )}

      {data.updatedAt && (
        <p className="text-xs text-muted-foreground">
          Last saved {new Date(data.updatedAt).toLocaleString()}
          {data.updatedBy ? ` by ${data.updatedBy}` : ""}.
        </p>
      )}
    </div>
  );
}
