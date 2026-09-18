"use client";

import { useState, type ReactNode } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import {
  CheckCircle,
  Cpu,
  Lock,
  Warning,
} from "@phosphor-icons/react/dist/ssr";

import type { ParsingSettings, ParsingTestResult } from "@/lib/types";
import { endpoints } from "@/lib/endpoints";
import { ProxyError, errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { cn } from "@/lib/utils";

type Profile = "low" | "medium" | "high";

const PROFILE_CARDS: { key: Profile; label: string }[] = [
  { key: "low", label: "Low" },
  { key: "medium", label: "Medium" },
  { key: "high", label: "High" },
];

const BOOL_FIELDS = ["tables", "formulas", "imageAnalysis"] as const;
const INT_FIELDS = ["windowPages", "windowTimeoutSeconds", "waitMaxSeconds"] as const;

const FIELD_META: Record<string, { label: string; hint?: string; placeholder?: string }> = {
  url: {
    label: "Parser URL",
    hint: "Empty turns parsing off â€” extraction reads PDFs directly. Compose uses http://mineru:8000 on the gpu profile.",
    placeholder: "http://mineru:8000",
  },
  backend: { label: "Backend" },
  effort: {
    label: "Effort",
    hint: "Only applies to hybrid-engine.",
  },
  method: { label: "Parse method" },
  lang: { label: "Language", placeholder: "en" },
  tables: { label: "Tables" },
  formulas: { label: "Formulas" },
  imageAnalysis: { label: "Image analysis" },
  windowPages: {
    label: "Pages per window",
    hint: "How many pages MinerU processes in one request (1â€“200).",
  },
  windowTimeoutSeconds: {
    label: "Window timeout (seconds)",
    hint: "60â€“7200. How long one MinerU window may take.",
  },
  waitMaxSeconds: {
    label: "Extraction wait max (seconds)",
    hint: "60â€“7200. How long extract jobs wait for parsing before proceeding.",
  },
};

const ENV_NAMES: Record<string, string> = {
  url: "PARSER_URL",
  profile: "PARSER_PROFILE",
  backend: "PARSER_BACKEND",
  effort: "PARSER_EFFORT",
  method: "PARSER_METHOD",
  lang: "PARSER_LANG",
  tables: "PARSER_TABLES",
  formulas: "PARSER_FORMULAS",
  imageAnalysis: "PARSER_IMAGE_ANALYSIS",
  windowPages: "PARSER_WINDOW_PAGES",
  windowTimeoutSeconds: "PARSER_WINDOW_TIMEOUT_SECONDS",
  waitMaxSeconds: "PARSER_WAIT_MAX_SECONDS",
};

/**
 * Declared at module scope, not inside the screen.
 *
 * A component created during render is a new type on every pass, so React
 * remounts it and it loses its state. Whether a field is locked by the
 * environment comes in as a prop rather than off a closure.
 */
function LockedBadge() {
  return (
    <span className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest bg-panel border border-subtle text-tx-muted shadow-sm">
      <Lock size={10} weight="bold" />
      set by env
    </span>
  );
}

function FieldLabel({
  fieldKey,
  locked,
  children,
}: {
  fieldKey: string;
  locked?: boolean;
  children?: ReactNode;
}) {
  const meta = FIELD_META[fieldKey];
  return (
    <span className="flex flex-wrap items-center gap-2 text-[12.5px] font-semibold text-tx-primary">
      {meta?.label ?? fieldKey}
      <code className="text-[11px] font-medium text-tx-muted px-1.5 py-0.5 rounded bg-panel-muted border border-subtle">
        {ENV_NAMES[fieldKey] ?? fieldKey}
      </code>
      {locked && <LockedBadge />}
      {children}
    </span>
  );
}


type Draft = {
  url: string;
  profile: Profile;
  backend: string;
  effort: string;
  method: string;
  lang: string;
  tables: boolean;
  formulas: boolean;
  imageAnalysis: boolean;
  windowPages: string;
  windowTimeoutSeconds: string;
  waitMaxSeconds: string;
};

function draftFromSettings(data: ParsingSettings, profileOverride?: Profile): Draft {
  const fields = data.fields;
  const profile = (profileOverride ?? (fields.profile?.value as Profile) ?? "low") as Profile;
  const preset = data.presets[profile];

  // Picking a profile fills unlocked runtime knobs from that preset; URL stays as-is.
  if (profileOverride && preset) {
    return {
      url: String(fields.url?.value ?? ""),
      profile,
      backend: fields.backend?.locked ? String(fields.backend.value ?? "") : preset.backend,
      effort: fields.effort?.locked
        ? String(fields.effort.value ?? "")
        : String(preset.effort ?? ""),
      method: fields.method?.locked ? String(fields.method.value ?? "") : preset.method,
      lang: fields.lang?.locked ? String(fields.lang.value ?? "") : preset.lang,
      tables: fields.tables?.locked ? Boolean(fields.tables.value) : preset.tables,
      formulas: fields.formulas?.locked ? Boolean(fields.formulas.value) : preset.formulas,
      imageAnalysis: fields.imageAnalysis?.locked
        ? Boolean(fields.imageAnalysis.value)
        : preset.imageAnalysis,
      windowPages: fields.windowPages?.locked
        ? String(fields.windowPages.value ?? "")
        : String(preset.windowPages),
      windowTimeoutSeconds: fields.windowTimeoutSeconds?.locked
        ? String(fields.windowTimeoutSeconds.value ?? "")
        : String(preset.windowTimeoutSeconds),
      waitMaxSeconds: fields.waitMaxSeconds?.locked
        ? String(fields.waitMaxSeconds.value ?? "")
        : String(preset.waitMaxSeconds),
    };
  }

  return {
    url: String(fields.url?.value ?? ""),
    profile,
    backend: String(fields.backend?.value ?? preset?.backend ?? "pipeline"),
    effort: String(fields.effort?.value ?? ""),
    method: String(fields.method?.value ?? "auto"),
    lang: String(fields.lang?.value ?? "en"),
    tables: Boolean(fields.tables?.value),
    formulas: Boolean(fields.formulas?.value),
    imageAnalysis: Boolean(fields.imageAnalysis?.value),
    windowPages: String(fields.windowPages?.value ?? ""),
    windowTimeoutSeconds: String(fields.windowTimeoutSeconds?.value ?? ""),
    waitMaxSeconds: String(fields.waitMaxSeconds?.value ?? ""),
  };
}

/**
 * MinerU runtime knobs for the next parse job.
 *
 * Process env still wins — locked fields match Claude settings. Container
 * sizing (VRAM, concurrent requests) is read-only from MinerU /health.
 */
export function ParsingSettingsClient() {
  const { data, error, mutate, isLoading } = useSWR<ParsingSettings>(
    endpoints.parsingSettings(),
    proxyFetcher,
  );

  const [edits, setEdits] = useState<{ key: string; values: Draft } | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ParsingTestResult | null>(null);

  if (error) {
    const forbidden = error instanceof ProxyError && error.status === 403;
    return (
      <div className="px-7 py-6">
        <div className="rounded-lg px-4 py-3 text-[13px] font-medium bg-status-error-soft border border-status-error/30 text-status-error shadow-sm">
          {forbidden
            ? "You do not have permission to configure the parser. Ask whoever administers this installation."
            : `Could not read the configuration: ${errorMessage(error)}`}
        </div>
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div className="px-7 py-6 text-[13px] font-medium text-tx-muted">
        Reading the current configurationâ€¦
      </div>
    );
  }

  const settings = data;
  const draftKey = `${settings.updatedAt ?? ""}`;
  const draft = edits?.key === draftKey ? edits.values : draftFromSettings(settings);
  const hybrid = draft.backend === "hybrid-engine";

  function setDraft(patch: Partial<Draft>) {
    setEdits({ key: draftKey, values: { ...draft, ...patch } });
  }

  function pickProfile(next: Profile) {
    if (settings.fields.profile?.locked) return;
    setResult(null);
    setEdits({ key: draftKey, values: draftFromSettings(settings, next) });
  }

  function payload(): Record<string, unknown> {
    const body: Record<string, unknown> = {};
    const fields = settings.fields;

    if (!fields.profile?.locked) body.profile = draft.profile;
    if (!fields.url?.locked) body.url = draft.url.trim();
    if (!fields.backend?.locked) body.backend = draft.backend;
    if (!fields.effort?.locked) {
      body.effort = hybrid && draft.effort ? draft.effort : null;
    }
    if (!fields.method?.locked) body.method = draft.method;
    if (!fields.lang?.locked) body.lang = draft.lang.trim() || "en";
    for (const key of BOOL_FIELDS) {
      if (!fields[key]?.locked) body[key] = draft[key];
    }
    for (const key of INT_FIELDS) {
      if (!fields[key]?.locked) {
        const n = Number(draft[key]);
        if (Number.isFinite(n)) body[key] = n;
      }
    }
    return body;
  }

  async function save() {
    setSaving(true);
    try {
      await proxyMutate(endpoints.parsingSettings(), { method: "PUT", body: payload() });
      toast.success("Parser settings saved", {
        description: "The next parse job will use them â€” no restart needed.",
      });
      setEdits(null);
      setResult(null);
      mutate();
    } catch (problem) {
      toast.error("Could not save that", { description: errorMessage(problem) });
    } finally {
      setSaving(false);
    }
  }

  async function test() {
    setTesting(true);
    setResult(null);
    try {
      const body = await proxyMutate<ParsingTestResult>(endpoints.parsingSettingsTest(), {
        body: payload(),
      });
      setResult(body);
      if (body.ok) {
        toast.success("Sample page parsed", {
          description: `${body.blocks ?? 0} blocks in ${body.seconds ?? "?"}s`,
        });
      } else {
        toast.error("Parser test failed", { description: body.error ?? undefined });
      }
    } catch (problem) {
      toast.error("Could not reach the API", { description: errorMessage(problem) });
    } finally {
      setTesting(false);
    }
  }



  const mineru = settings.mineru;
  const mineruError = mineru && typeof mineru.error === "string" ? mineru.error : null;

  return (
    <div className="flex flex-col gap-6 p-8 bg-panel border border-subtle rounded-xl shadow-sm">
      <header className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-4">
        <div>
          <h1 className="text-[20px] font-bold text-tx-primary tracking-tight">Document parser</h1>
          <p className="mt-1 text-[13px] font-medium text-tx-secondary">
            MinerU parses each uploaded PDF once on the GPU. Empty URL leaves parsing off.
            {settings.updatedBy ? ` Last changed by ${settings.updatedBy}.` : ""}
          </p>
        </div>
        <span
          className={cn(
            "flex items-center gap-2 rounded-md px-3 py-2 text-[12.5px] font-medium shadow-sm",
            settings.enabled || draft.url.trim()
              ? "bg-status-success-soft text-status-success"
              : "bg-panel-muted text-tx-muted border border-subtle",
          )}
        >
          <Cpu size={14} weight="duotone" />
          {draft.url.trim() ? "Parsing on" : "Parsing off"}
        </span>
      </header>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {PROFILE_CARDS.map(({ key, label }) => {
          const on = draft.profile === key;
          const hardware = settings.presets[key]?.hardware ?? "";
          const locked = Boolean(settings.fields.profile?.locked);
          return (
            <button
              key={key}
              type="button"
              disabled={locked}
              onClick={() => pickProfile(key)}
              className={cn(
                "flex flex-col items-start gap-2 rounded-xl p-4 text-left transition-colors shadow-sm disabled:opacity-60",
                on
                  ? "bg-brand-soft border-2 border-brand-primary"
                  : "bg-background border border-subtle hover:border-brand-border",
              )}
            >
              <span
                className={cn(
                  "text-[13.5px] font-bold tracking-tight",
                  on ? "text-brand-primary" : "text-tx-primary",
                )}
              >
                {label}
              </span>
              <span className="text-[12.5px] font-medium leading-snug text-tx-secondary">
                {hardware}
              </span>
            </button>
          );
        })}
      </div>
      {settings.fields.profile?.locked && (
        <p className="text-[12px] font-medium text-tx-muted -mt-3">
          Profile is set in the server environment.
        </p>
      )}

      <section className="flex flex-col gap-4 rounded-xl p-5 bg-background border border-subtle shadow-sm">
        <label className="flex flex-col gap-1.5">
          <FieldLabel fieldKey="url" locked={Boolean(settings.fields.url?.locked)} />
          <input
            value={draft.url}
            disabled={Boolean(settings.fields.url?.locked)}
            onChange={(event) => setDraft({ url: event.target.value })}
            placeholder={FIELD_META.url.placeholder}
            autoComplete="off"
            spellCheck={false}
            className="rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border disabled:opacity-60 shadow-sm"
          />
          {settings.fields.url?.locked ? (
            <span className="text-[12px] font-medium text-tx-muted">
              Set in the server environment
            </span>
          ) : (
            <span className="text-[12px] font-medium text-tx-muted">{FIELD_META.url.hint}</span>
          )}
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <FieldLabel fieldKey="backend" locked={Boolean(settings.fields.backend?.locked)} />
            <select
              value={draft.backend}
              disabled={Boolean(settings.fields.backend?.locked)}
              onChange={(event) => {
                const backend = event.target.value;
                setDraft({
                  backend,
                  effort: backend === "hybrid-engine" ? draft.effort || "medium" : "",
                });
              }}
              className="rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border disabled:opacity-60 shadow-sm"
            >
              {settings.backends.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
            {settings.fields.backend?.locked && (
              <span className="text-[12px] font-medium text-tx-muted">
                Set in the server environment
              </span>
            )}
          </label>

          {hybrid && (
            <label className="flex flex-col gap-1.5">
              <FieldLabel fieldKey="effort" locked={Boolean(settings.fields.effort?.locked)} />
              <select
                value={draft.effort || "medium"}
                disabled={Boolean(settings.fields.effort?.locked)}
                onChange={(event) => setDraft({ effort: event.target.value })}
                className="rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border disabled:opacity-60 shadow-sm"
              >
                {settings.efforts.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
              {settings.fields.effort?.locked ? (
                <span className="text-[12px] font-medium text-tx-muted">
                  Set in the server environment
                </span>
              ) : (
                <span className="text-[12px] font-medium text-tx-muted">{FIELD_META.effort.hint}</span>
              )}
            </label>
          )}

          <label className="flex flex-col gap-1.5">
            <FieldLabel fieldKey="method" locked={Boolean(settings.fields.method?.locked)} />
            <select
              value={draft.method}
              disabled={Boolean(settings.fields.method?.locked)}
              onChange={(event) => setDraft({ method: event.target.value })}
              className="rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border disabled:opacity-60 shadow-sm"
            >
              {settings.methods.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
            {settings.fields.method?.locked && (
              <span className="text-[12px] font-medium text-tx-muted">
                Set in the server environment
              </span>
            )}
          </label>

          <label className="flex flex-col gap-1.5">
            <FieldLabel fieldKey="lang" locked={Boolean(settings.fields.lang?.locked)} />
            <input
              value={draft.lang}
              disabled={Boolean(settings.fields.lang?.locked)}
              onChange={(event) => setDraft({ lang: event.target.value })}
              placeholder={FIELD_META.lang.placeholder}
              autoComplete="off"
              className="rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border disabled:opacity-60 shadow-sm"
            />
            {settings.fields.lang?.locked && (
              <span className="text-[12px] font-medium text-tx-muted">
                Set in the server environment
              </span>
            )}
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          {BOOL_FIELDS.map((key) => {
            const on = draft[key];
            const locked = Boolean(settings.fields[key]?.locked);
            return (
              <button
                key={key}
                type="button"
                disabled={locked}
                aria-pressed={on}
                onClick={() => setDraft({ [key]: !on })}
                className={cn(
                  "rounded-md px-3 py-2 text-[12.5px] font-semibold transition-colors shadow-sm disabled:opacity-60",
                  on
                    ? "bg-brand-primary/10 border border-brand-primary/20 text-brand-primary"
                    : "bg-panel border border-subtle text-tx-secondary hover:bg-panel-muted",
                )}
              >
                {FIELD_META[key].label}
                {locked ? " Â· env" : on ? " Â· on" : " Â· off"}
              </button>
            );
          })}
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          {INT_FIELDS.map((key) => (
            <label key={key} className="flex flex-col gap-1.5">
              <FieldLabel fieldKey={key} locked={Boolean(settings.fields[key]?.locked)} />
              <input
                type="number"
                value={draft[key]}
                disabled={Boolean(settings.fields[key]?.locked)}
                onChange={(event) => setDraft({ [key]: event.target.value })}
                className="rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border disabled:opacity-60 shadow-sm"
              />
              {settings.fields[key]?.locked ? (
                <span className="text-[12px] font-medium text-tx-muted">
                  Set in the server environment
                </span>
              ) : (
                FIELD_META[key].hint && (
                  <span className="text-[12px] font-medium text-tx-muted">
                    {FIELD_META[key].hint}
                  </span>
                )
              )}
            </label>
          ))}
        </div>
      </section>

      <section className="rounded-xl p-5 bg-panel-muted border border-subtle shadow-sm">
        <h2 className="text-[14px] font-bold text-tx-primary tracking-tight">MinerU container</h2>
        <p className="mt-1 text-[13px] font-medium text-tx-secondary">
          Read-only from MinerU /health. Change VRAM, concurrency, and base image in{" "}
          <code className="text-[12px]">infra/mineru/&lt;profile&gt;.env</code>, then rebuild.
        </p>
        {mineruError ? (
          <p className="mt-3 text-[13px] font-medium text-status-warning">{mineruError}</p>
        ) : mineru ? (
          <dl className="mt-4 grid gap-3 sm:grid-cols-2 text-[13px]">
            {[
              ["version", "Version"],
              ["max_concurrent_requests", "Max concurrent requests"],
              ["processing_window_size", "Processing window size"],
              ["queue_size", "Queue size"],
              ["pending_tasks", "Pending tasks"],
              ["running_tasks", "Running tasks"],
            ].map(([key, label]) => {
              const value = mineru[key];
              if (value === undefined || value === null) return null;
              return (
                <div key={key} className="flex flex-col gap-0.5">
                  <dt className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                    {label}
                  </dt>
                  <dd className="font-medium text-tx-primary tnum">{String(value)}</dd>
                </div>
              );
            })}
          </dl>
        ) : (
          <p className="mt-3 text-[13px] font-medium text-tx-muted">No health data yet.</p>
        )}
      </section>

      <div className="flex flex-wrap items-center gap-3 pt-2">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="rounded-md px-4 py-2.5 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-60"
        >
          {saving ? "Savingâ€¦" : "Save"}
        </button>
        <button
          type="button"
          onClick={test}
          disabled={testing}
          className="rounded-md px-4 py-2.5 text-[13px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm disabled:opacity-60"
        >
          {testing ? "Testingâ€¦" : "Test with a sample page"}
        </button>
        <span className="text-[12.5px] font-medium text-tx-muted">
          Test uses the values on screen, not what is saved.
        </span>
      </div>

      {result && (
        <div
          className={cn(
            "flex items-start gap-2.5 rounded-lg px-4 py-3 text-[12.5px] shadow-sm",
            result.ok
              ? "bg-status-success-soft border border-status-success/30 text-status-success"
              : "bg-status-error-soft border border-status-error/30 text-status-error",
          )}
        >
          {result.ok ? (
            <CheckCircle size={16} weight="duotone" className="mt-0.5 shrink-0" />
          ) : (
            <Warning size={16} weight="duotone" className="mt-0.5 shrink-0" />
          )}
          <span>
            {result.ok ? (
              <>
                Parsed sample page
                {result.backend ? (
                  <>
                    {" "}
                    with <strong className="font-bold">{result.backend}</strong>
                  </>
                ) : null}
                {result.blocks != null ? <> Â· {result.blocks} blocks</> : null}
                {result.seconds != null ? <> Â· {result.seconds}s</> : null}
                {result.version ? <> Â· MinerU {result.version}</> : null}.
              </>
            ) : (
              result.error
            )}
          </span>
        </div>
      )}
    </div>
  );
}
