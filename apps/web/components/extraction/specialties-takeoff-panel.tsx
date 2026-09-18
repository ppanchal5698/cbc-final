"use client";

import { useState } from "react";
import useSWR from "swr";
import { CaretDown, CaretRight } from "@phosphor-icons/react/dist/ssr";

import { proxyFetcher } from "@/lib/proxy-fetcher";
import type { SpecialtyTakeoff, TakeoffsResponse } from "@/lib/types";

function isFrp(row: SpecialtyTakeoff): boolean {
  const t = (row.takeoffType || "").toLowerCase();
  return t === "frp" || t === "frparea" || t.includes("frp");
}

function isDiv10(row: SpecialtyTakeoff): boolean {
  const t = (row.takeoffType || "").toLowerCase();
  return t === "accessorycount" || t === "div10" || t === "accessory";
}

export function SpecialtiesTakeoffPanel({ code }: { code: string }) {
  const { data, error, isLoading } = useSWR<TakeoffsResponse>(
    `/api/proxy/projects/${code}/takeoffs`,
    proxyFetcher,
  );
  const [open, setOpen] = useState(true);

  const rows = data?.takeoffs ?? [];
  const frpInScope = Boolean(data?.frpInScope);
  const div10InScope = Boolean(data?.div10InScope);
  const frp = rows.filter(isFrp);
  const div10 = rows.filter(isDiv10);
  const other = rows.filter((row) => !isFrp(row) && !isDiv10(row));
  const inScope = frpInScope || div10InScope;

  if (isLoading) {
    return (
      <section className="shrink-0 rounded-xl border border-subtle bg-panel p-4 shadow-sm">
        <h2 className="text-[13px] font-bold uppercase tracking-widest text-tx-muted">
          Specialties takeoff
        </h2>
        <p className="mt-2 text-[13px] text-tx-muted animate-pulse">Loading specialties…</p>
      </section>
    );
  }

  // Hide only when out of scope and nothing was recorded. In-scope empty runs
  // must stay visible so estimators know FRP / Div 10 did not land as doors.
  if (error || (!inScope && rows.length === 0)) {
    return null;
  }

  const summaryParts: string[] = [];
  if (div10.length) summaryParts.push(`${div10.length} Div 10`);
  else if (div10InScope) summaryParts.push("Div 10 pending");
  if (frp.length) summaryParts.push(`${frp.length} FRP`);
  else if (frpInScope) summaryParts.push("FRP pending");
  if (other.length) summaryParts.push(`${other.length} other`);
  const summary = summaryParts.join(" · ") || "In scope";

  return (
    <section className="flex min-h-0 shrink-0 flex-col overflow-hidden rounded-xl border border-subtle bg-panel shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-panel-muted/40 transition-colors"
        aria-expanded={open}
      >
        {open ? (
          <CaretDown size={14} weight="bold" className="shrink-0 text-tx-muted" />
        ) : (
          <CaretRight size={14} weight="bold" className="shrink-0 text-tx-muted" />
        )}
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="text-[13px] font-bold uppercase tracking-widest text-tx-muted">
            Specialties takeoff
          </span>
          <span className="truncate text-[12px] font-medium text-tx-secondary">
            {summary}
            {!open ? " — door openings are below" : ""}
          </span>
        </span>
      </button>

      {open && (
        <div className="max-h-[min(220px,28vh)] overflow-y-auto border-t border-subtle px-4 pb-3 custom-scrollbar">
          <p className="mt-2 text-[12.5px] text-tx-secondary">
            Division 10 counts and FRP geometry — separate from door openings in
            the table below. Hardware set parts are priced later, not listed here.
          </p>

          {div10InScope && div10.length === 0 && (
            <p className="mt-3 text-[13px] text-status-warning">
              Division 10 is in scope, but no specialty rows were imported yet.
              Re-run extraction after the Div 10 pass finishes, or add counts by
              hand.
            </p>
          )}

          {frpInScope && frp.length === 0 && (
            <p className="mt-3 text-[13px] text-status-warning">
              FRP is in scope, but no wall-panel geometry was imported yet. Re-run
              extraction after the FRP pass finishes, or measure in Vu360.
            </p>
          )}

          {div10.length > 0 && (
            <div className="mt-3">
              <h3 className="text-[12px] font-bold uppercase tracking-widest text-tx-muted">
                Division 10
              </h3>
              <ul className="mt-1 divide-y divide-subtle">
                {div10.map((row) => (
                  <li key={row.id} className="py-2 text-[13px] text-tx-secondary">
                    <span className="font-semibold text-tx-primary">
                      {row.productType ?? "item"}
                      {row.qty != null ? ` × ${row.qty}` : ""}
                      {row.unit ? ` ${row.unit}` : ""}
                    </span>
                    {row.manufacturer ? ` · ${row.manufacturer}` : ""}
                    {row.specifiedModel ? ` · ${row.specifiedModel}` : ""}
                    {row.location ? ` · ${row.location}` : ""}
                    {row.sourceRef?.sourcePage != null
                      ? ` · p.${row.sourceRef.sourcePage}`
                      : ""}
                    {row.status ? ` · ${row.status}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {frp.length > 0 && (
            <div className="mt-3">
              <h3 className="text-[12px] font-bold uppercase tracking-widest text-tx-muted">
                FRP
              </h3>
              <ul className="mt-1 divide-y divide-subtle">
                {frp.map((row) => (
                  <li key={row.id} className="py-2 text-[13px] text-tx-secondary">
                    <span className="font-semibold text-tx-primary">
                      {row.location ?? row.productType ?? "FRP area"}
                    </span>
                    {row.manufacturer ? ` · ${row.manufacturer}` : ""}
                    {row.perimeterLf != null ? ` · ${row.perimeterLf} lf` : ""}
                    {row.insideCorners != null ? ` · ${row.insideCorners} IC` : ""}
                    {row.outsideCorners != null ? ` · ${row.outsideCorners} OC` : ""}
                    {row.wallHeightFt != null ? ` · ${row.wallHeightFt} ft high` : ""}
                    {row.drawingScale ? ` · scale ${row.drawingScale}` : ""}
                    {row.sourceRef?.sourcePage != null
                      ? ` · p.${row.sourceRef.sourcePage}`
                      : ""}
                    {row.status ? ` · ${row.status}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {other.length > 0 && (
            <div className="mt-3">
              <h3 className="text-[12px] font-bold uppercase tracking-widest text-tx-muted">
                Other takeoffs
              </h3>
              <ul className="mt-1 divide-y divide-subtle">
                {other.map((row) => (
                  <li key={row.id} className="py-2 text-[13px] text-tx-secondary">
                    {row.takeoffType ?? "takeoff"}
                    {row.location ? ` · ${row.location}` : ""}
                    {row.status ? ` · ${row.status}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
