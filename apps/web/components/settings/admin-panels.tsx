"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";

import { useDebounced } from "@/hooks/use-debounced";
import { useUiState } from "@/components/shell/ui-state";
import { FetchError } from "@/components/ui/fetch-error";
import { StatusBadge } from "@/components/ui/status-badge";
import { endpoints } from "@/lib/endpoints";
import { isAdminRole } from "@/lib/job-error";
import { swrKeys } from "@/lib/swr-keys";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { AuditEntry, FreshnessSettings, IntegrationsResponse, PipelineSettings, UserRow } from "@/lib/types";
import { cn } from "@/lib/utils";

export function AuditLogPanel() {
  const [project, setProject] = useState("");
  const settled = useDebounced(project.trim());
  const query = settled
    ? `/api/proxy/audit?limit=50&project=${encodeURIComponent(settled)}`
    : "/api/proxy/audit?limit=50";

  const { data, error, isLoading } = useSWR<{ entries: AuditEntry[]; total: number }>(
    query,
    proxyFetcher,
    { keepPreviousData: true },
  );

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm">
      <div className="border-b border-subtle px-5 py-4">
        <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Audit log</h2>
        <p className="mt-1 text-[13px] font-medium text-tx-secondary">
          Who changed what — administrators only.
        </p>
        <input
          value={project}
          onChange={(event) => setProject(event.target.value)}
          placeholder="Filter by bid code, e.g. bid_12"
          aria-label="Filter the audit log by bid code"
          className="mt-4 w-full max-w-xs rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
        />
      </div>

      <div className="max-h-[420px] overflow-y-auto divide-y divide-subtle">
        {error && (
          <p className="px-5 py-6 text-[13px] font-medium text-status-error">
            Could not read the audit log: {errorMessage(error)}
          </p>
        )}
        {isLoading && !data && (
          <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
            Loading…
          </p>
        )}
        {(data?.entries ?? []).map((entry) => (
          <div
            key={entry.id}
            className="flex gap-4 px-5 py-3 hover:bg-panel-muted transition-colors"
          >
            <time className="tnum shrink-0 text-[12px] font-medium text-tx-muted w-[140px]">
              {new Date(entry.at).toLocaleString()}
            </time>
            <span className="shrink-0 text-[12.5px] font-semibold text-tx-primary w-[140px]">
              {entry.actor}
            </span>
            <span className="text-[13px] font-medium text-tx-secondary">
              {entry.action}
              {entry.note ? ` — ${entry.note}` : ""}
            </span>
          </div>
        ))}
        {!isLoading && !error && (data?.entries.length ?? 0) === 0 && (
          <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
            No entries yet.
          </p>
        )}
      </div>
      {data && (
        <p className="border-t border-subtle bg-panel-muted px-5 py-2.5 text-[11.5px] font-medium text-tx-muted rounded-b-xl">
          Showing {data.entries.length} of {data.total}
        </p>
      )}
    </section>
  );
}

export function UsersAdminPanel() {
  const { data, error, isLoading, mutate } = useSWR<{ users: UserRow[] }>(
    "/api/proxy/users",
    proxyFetcher,
  );
  const [draft, setDraft] = useState({
    email: "",
    name: "",
    initials: "",
    role: "estimator",
    password: "",
  });
  const [busy, setBusy] = useState(false);

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await proxyMutate("/api/proxy/users", { body: draft });
      toast.success(`${draft.email} added`);
      setDraft({ email: "", name: "", initials: "", role: "estimator", password: "" });
      mutate();
    } catch (problem) {
      toast.error("Could not create user", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  async function updateRole(user: UserRow, role: string) {
    try {
      await proxyMutate(`/api/proxy/users/${user.id}`, { method: "PATCH", body: { role } });
      toast.success(`${user.name} is now ${role}`);
      mutate();
    } catch (problem) {
      toast.error("Could not update role", { description: errorMessage(problem) });
      // Put the select back where it was; the change did not happen.
      mutate();
    }
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm">
      <div className="border-b border-subtle px-5 py-4">
        <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Users</h2>
        <p className="mt-1 text-[13px] font-medium text-tx-secondary">
          Accounts and roles for this installation.
        </p>
      </div>

      <form
        onSubmit={createUser}
        className="grid gap-3 border-b border-subtle bg-panel-muted px-5 py-4 sm:grid-cols-2"
      >
        {(
          [
            ["email", "Email", "email"],
            ["name", "Name", "text"],
            ["initials", "Initials", "text"],
            ["password", "Password", "password"],
          ] as const
        ).map(([key, label, type]) => (
          <label key={key} className="text-[12px] font-bold uppercase tracking-widest text-tx-muted flex flex-col gap-1.5">
            {label}
            <input
              type={type}
              required
              value={draft[key]}
              onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
              className="mt-0.5 block w-full rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm normal-case tracking-normal"
            />
          </label>
        ))}
        <label className="text-[12px] font-bold uppercase tracking-widest text-tx-muted flex flex-col gap-1.5">
          Role
          <select
            value={draft.role}
            onChange={(event) => setDraft({ ...draft, role: event.target.value })}
            className="mt-0.5 block w-full rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm normal-case tracking-normal"
          >
            <option value="estimator">estimator</option>
            <option value="admin">admin</option>
          </select>
        </label>
        <div className="flex items-end">
          <button
            type="submit"
            disabled={busy}
            className="w-full sm:w-auto rounded-md px-4 py-2 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-50"
          >
            Add user
          </button>
        </div>
      </form>

      {error && (
        <div className="p-4">
          <FetchError
            title="Could not load users"
            error={error}
            onRetry={() => mutate()}
            compact
          />
        </div>
      )}
      {isLoading && !data && !error && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
          Loading users…
        </p>
      )}

      <div className="divide-y divide-subtle">
        {(data?.users ?? []).map((user) => (
          <div key={user.id} className="flex items-center gap-4 px-5 py-3 hover:bg-panel-muted transition-colors">
            <div className="flex-1">
              <div className="text-[14px] font-semibold text-tx-primary">{user.name}</div>
              <div className="text-[12.5px] font-medium text-tx-secondary mt-0.5">
                {user.email}
              </div>
            </div>
            <select
              value={user.role}
              aria-label={`Role for ${user.name}`}
              onChange={(event) => updateRole(user, event.target.value)}
              className="rounded-md px-2.5 py-1.5 text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
            >
              <option value="estimator">estimator</option>
              <option value="admin">admin</option>
            </select>
          </div>
        ))}
      </div>
    </section>
  );
}

export function PipelineSettingsPanel() {
  const { data, error, isLoading, mutate } = useSWR<PipelineSettings>(
    swrKeys.pipelineSettings(),
    proxyFetcher,
  );
  const [busy, setBusy] = useState(false);

  async function toggleAutopilot() {
    if (!data) return;
    setBusy(true);
    try {
      await proxyMutate<PipelineSettings>(endpoints.pipelineSettings(), {
        method: "PUT",
        body: { autopilotDefault: !data.autopilotDefault },
      });
      toast.success(
        !data.autopilotDefault
          ? "Autopilot enabled for new bids"
          : "Autopilot disabled for new bids",
      );
      mutate();
    } catch (problem) {
      toast.error("Could not save pipeline settings", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm">
      <div className="border-b border-subtle px-5 py-4">
        <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Pipeline defaults</h2>
        <p className="mt-1 text-[13px] font-medium text-tx-secondary">
          Global defaults for new bids. Each bid can override autopilot at creation.
        </p>
      </div>

      {error && (
        <div className="p-4">
          <FetchError
            title="Could not load pipeline settings"
            error={error}
            onRetry={() => mutate()}
            compact
          />
        </div>
      )}
      {isLoading && !data && !error && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
          Loading…
        </p>
      )}
      {data && (
        <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-5">
          <div className="max-w-[520px]">
            <p className="text-[14px] font-semibold text-tx-primary">Autopilot default for new bids</p>
            <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
              {data.note ??
                "When enabled, uploading a drawing runs Phase 0–6 in one pass. Nothing is ever sent."}
            </p>
            {data.updatedBy && (
              <p className="mt-3 text-[11.5px] font-medium text-tx-muted">
                Last changed by {data.updatedBy}
                {data.updatedAt ? ` · ${new Date(data.updatedAt).toLocaleString()}` : ""}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={toggleAutopilot}
            disabled={busy}
            aria-pressed={data.autopilotDefault}
            className={cn(
              "rounded-md px-4 py-2.5 text-[13px] font-semibold disabled:opacity-50 transition-colors shadow-sm",
              data.autopilotDefault
                ? "bg-brand-primary text-white hover:bg-brand-primary/90"
                : "bg-panel border border-subtle text-tx-secondary hover:bg-panel-muted"
            )}
          >
            {busy ? "Saving…" : data.autopilotDefault ? "Autopilot on" : "Autopilot off"}
          </button>
        </div>
      )}
    </section>
  );
}

export function FreshnessSettingsPanel() {
  const { data, error, isLoading, mutate } = useSWR<FreshnessSettings>(
    swrKeys.freshnessSettings(),
    proxyFetcher,
  );
  const [busy, setBusy] = useState(false);
  const [catalogMonths, setCatalogMonths] = useState("");
  const [discardMonths, setDiscardMonths] = useState("");

  const catalogValue = catalogMonths !== "" ? catalogMonths : String(data?.catalogStaleMonths ?? "");
  const discardValue = discardMonths !== "" ? discardMonths : String(data?.discardAfterMonths ?? "");

  async function save() {
    const catalogStaleMonths = Number(catalogValue);
    const discardAfterMonths = Number(discardValue);
    if (
      !Number.isInteger(catalogStaleMonths) ||
      !Number.isInteger(discardAfterMonths) ||
      catalogStaleMonths < 1 ||
      discardAfterMonths > 120 ||
      catalogStaleMonths >= discardAfterMonths
    ) {
      toast.error("Check the month values", {
        description: "Review window must be at least 1 month and shorter than the discard band (max 120).",
      });
      return;
    }
    setBusy(true);
    try {
      await proxyMutate<FreshnessSettings>(endpoints.freshnessSettings(), {
        method: "PUT",
        body: { catalogStaleMonths, discardAfterMonths },
      });
      toast.success(
        `Price books stale after ${catalogStaleMonths} months; last-PO discarded after ${discardAfterMonths}`,
      );
      setCatalogMonths("");
      setDiscardMonths("");
      mutate();
    } catch (problem) {
      toast.error("Could not save freshness settings", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm">
      <div className="border-b border-subtle px-5 py-4">
        <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Price book freshness</h2>
        <p className="mt-1 text-[13px] font-medium text-tx-secondary">
          How long vendor catalogs and price books stay inside the review window.
          P21 last-PO costs use the same fresh window, then the discard band.
        </p>
      </div>

      {error && (
        <div className="p-4">
          <FetchError
            title="Could not load freshness settings"
            error={error}
            onRetry={() => mutate()}
            compact
          />
        </div>
      )}
      {isLoading && !data && !error && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
          Loading…
        </p>
      )}
      {data && (
        <div className="flex flex-col gap-5 px-5 py-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-semibold text-tx-primary">
                Catalog / price-book review window (months)
              </span>
              <input
                type="number"
                min={1}
                max={119}
                step={1}
                value={catalogValue}
                onChange={(event) => setCatalogMonths(event.target.value)}
                className="rounded-md px-2.5 py-2 text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border shadow-sm tnum"
              />
              <span className="text-[12px] font-medium text-tx-muted">
                Sheets older than this show as stale. Default 24.
              </span>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-semibold text-tx-primary">
                P21 last-PO discard after (months)
              </span>
              <input
                type="number"
                min={2}
                max={120}
                step={1}
                value={discardValue}
                onChange={(event) => setDiscardMonths(event.target.value)}
                className="rounded-md px-2.5 py-2 text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border shadow-sm tnum"
              />
              <span className="text-[12px] font-medium text-tx-muted">
                Last-PO costs older than this are discarded. Default 30 (2.5 years).
              </span>
            </label>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[12.5px] font-medium text-tx-secondary max-w-[520px]">
              {data.rule ?? data.note}
              {data.updatedBy ? (
                <span className="block mt-1.5 text-[11.5px] text-tx-muted">
                  Last changed by {data.updatedBy}
                  {data.updatedAt ? ` · ${new Date(data.updatedAt).toLocaleString()}` : ""}
                </span>
              ) : null}
            </p>
            <button
              type="button"
              onClick={save}
              disabled={busy}
              className="rounded-md px-4 py-2.5 text-[13px] font-semibold bg-brand-primary text-white hover:bg-brand-primary/90 disabled:opacity-50 transition-colors shadow-sm"
            >
              {busy ? "Saving…" : "Save freshness"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

export function IntegrationsPanel() {
  const { userRole } = useUiState();
  const { data, error, isLoading } = useSWR<IntegrationsResponse>(
    endpoints.integrations(),
    proxyFetcher,
  );
  const p21 = data?.p21;

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm">
      <div className="border-b border-subtle px-5 py-4">
        <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Integrations</h2>
        <p className="mt-1 text-[13px] font-medium text-tx-secondary">
          External systems that feed purchase-order costs and price freshness.
        </p>
      </div>

      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not load integration status: {errorMessage(error)}
        </p>
      )}
      {isLoading && !data && !error && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
          Loading…
        </p>
      )}

      {p21 && (
        <div className="px-5 py-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-[560px]">
              <p className="text-[14px] font-semibold text-tx-primary">{p21.title}</p>
              <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
                {p21.summary}
              </p>
            </div>
            {p21.connected ? (
              <StatusBadge variant="ok">Connected</StatusBadge>
            ) : (
              <StatusBadge variant="caution" dashed>
                Not connected
              </StatusBadge>
            )}
          </div>
          <p className="mt-4 rounded-md px-4 py-3 text-[13px] font-medium leading-relaxed bg-panel-muted border border-subtle text-tx-secondary shadow-sm">
            {p21.note}
            {isAdminRole(userRole) && p21.adminNote && (
              <span className="mt-2.5 block text-[12px] text-tx-muted">
                {p21.adminNote}
              </span>
            )}
          </p>
          {!p21.connected && p21.fallbacks && p21.fallbacks.length > 0 && (
            <ul className="mt-3 list-disc pl-5 text-[12px] font-medium text-tx-muted space-y-1">
              {p21.fallbacks.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
