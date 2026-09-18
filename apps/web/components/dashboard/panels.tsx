/**
 * The dashboard's roll-up panels.
 *
 * All server-rendered: every one is a read of the Project rows the page already
 * fetched, so none of them needs state, an effect or a second request. The
 * numbers come from lib/board.ts, so the board's chips and these panels cannot
 * drift apart.
 */
import Link from "next/link";
import {
  ChartBar,
  Trophy,
  CalendarBlank,
  UsersThree,
  Receipt,
  Buildings,
} from "@phosphor-icons/react/dist/ssr";

import {
  PIPELINE_STAGES,
  boardStatus,
  daysUntil,
  dueLabel,
  estimatorLabel,
  groupBy,
  isLive,
  outcomeCounts,
  sumValue,
  type BoardStatus,
} from "@/lib/board";
import { formatMoneyShort } from "@/lib/format";
import type { Project } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Shared chrome, so six panels line up without six copies of the header. */
export function Panel({
  title,
  icon,
  action,
  children,
  className,
}: {
  title: string;
  icon: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "flex min-w-0 flex-col overflow-hidden rounded-xl border border-subtle bg-panel shadow-1",
        className,
      )}
    >
      <div className="flex items-center gap-3 border-b border-subtle px-5 py-3.5">
        <span className="text-brand-primary">{icon}</span>
        <span className="text-[14px] font-semibold tracking-tight text-tx-primary">{title}</span>
        <span className="flex-1" />
        {action}
      </div>
      {children}
    </section>
  );
}

const STATUS_TONE: Record<BoardStatus, string> = {
  Intake: "text-brand-primary",
  Extracting: "text-status-info",
  Review: "text-status-warning",
  "In progress": "text-brand-primary",
  Sent: "text-status-success",
  Closed: "text-tx-muted",
  Shelved: "text-tx-muted",
};

export function PipelineByStage({ projects }: { projects: Project[] }) {
  const live = projects.filter(isLive);
  const inFlight = sumValue(live);
  const byStage = PIPELINE_STAGES.map((stage) => {
    const rows = projects.filter((project) => boardStatus(project) === stage);
    return { stage, count: rows.length, total: sumValue(rows) };
  });
  // Bars are relative to the fullest stage, not to the total: the question this
  // panel answers is where work is piling up, not what share each stage holds.
  const busiest = Math.max(1, ...byStage.map((row) => row.count));

  return (
    <Panel title="Pipeline by stage" icon={<ChartBar size={17} weight="duotone" />}>
      <div className="border-b border-subtle px-5 py-4">
        <div className="tnum text-[26px] font-bold leading-none text-tx-primary">
          {formatMoneyShort(inFlight)}
        </div>
        <div className="mt-1.5 text-[12.5px] font-medium text-tx-secondary">
          {live.length} live bid{live.length === 1 ? "" : "s"}
          {live.length > 0
            ? ` · ${formatMoneyShort(Math.round(inFlight / live.length))} average`
            : ""}
        </div>
      </div>
      <div className="flex flex-col gap-1 p-3">
        {byStage.map(({ stage, count, total }) => (
          <Link
            key={stage}
            href={`/bids?status=${encodeURIComponent(stage)}`}
            className="grid items-center gap-3 rounded-lg px-2 py-2 no-underline transition-colors hover:bg-panel-muted"
            style={{ gridTemplateColumns: "112px minmax(0,1fr) 26px 76px" }}
          >
            <span
              className={cn(
                "truncate text-[12.5px] font-medium",
                count ? STATUS_TONE[stage] : "text-tx-muted",
              )}
            >
              {stage}
            </span>
            <span className="h-1.5 overflow-hidden rounded-full bg-panel-muted">
              <span
                className={cn("block h-full rounded-full", count ? "bg-brand-primary" : "bg-subtle")}
                style={{ width: `${Math.round((count / busiest) * 100)}%` }}
              />
            </span>
            <span className="tnum text-right text-[12.5px] font-bold text-tx-primary">{count}</span>
            <span className="tnum text-right text-[12px] font-medium text-tx-muted">
              {formatMoneyShort(total)}
            </span>
          </Link>
        ))}
      </div>
    </Panel>
  );
}

export function WonLostNotBid({ projects }: { projects: Project[] }) {
  const { won, lost, notBid, decided, winRate } = outcomeCounts(projects);
  const wonTurn = decided ? won / decided : 0;

  return (
    <Panel title="Won, lost and not bid" icon={<Trophy size={17} weight="duotone" />}>
      <div
        className="grid items-center gap-5 p-5"
        style={{ gridTemplateColumns: "124px minmax(0,1fr)" }}
      >
        <div
          className="grid h-[124px] w-[124px] place-items-center rounded-full"
          style={{
            background: decided
              ? `conic-gradient(var(--status-success) 0turn ${wonTurn}turn, var(--status-error) ${wonTurn}turn 1turn)`
              : "var(--panel-muted)",
          }}
        >
          <span className="grid h-[94px] w-[94px] place-items-center rounded-full bg-panel">
            <span className="flex flex-col items-center leading-tight">
              <span className="tnum text-[24px] font-bold text-tx-primary">
                {winRate === null ? "—" : `${winRate}%`}
              </span>
              <span className="mt-0.5 text-[11px] font-medium uppercase tracking-wider text-tx-muted">
                {decided} decided
              </span>
            </span>
          </span>
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          {[
            { label: "Won", n: won, tone: "text-status-success", href: "/bids?outcome=won" },
            { label: "Lost", n: lost, tone: "text-status-error", href: "/bids?outcome=lost" },
            { label: "Not bid", n: notBid, tone: "text-tx-secondary", href: "/bids?bid=not_bid" },
          ].map((row) => (
            <Link
              key={row.label}
              href={row.href}
              className="flex items-center gap-3 rounded-md px-2 py-1.5 no-underline transition-colors hover:bg-panel-muted"
            >
              <span className={cn("flex-1 text-[13px] font-medium", row.tone)}>{row.label}</span>
              <span className="tnum text-[14px] font-bold text-tx-primary">{row.n}</span>
            </Link>
          ))}
          <p className="mt-1.5 px-2 text-[11.5px] leading-relaxed text-tx-muted">
            {notBid} job{notBid === 1 ? "" : "s"} went unworked. Held apart from win rate &mdash;
            never counted as lost.
          </p>
        </div>
      </div>
    </Panel>
  );
}

export function DueNext({ projects }: { projects: Project[] }) {
  const due = projects
    .filter((project) => isLive(project) && project.bidDue)
    .sort((a, b) => String(a.bidDue).localeCompare(String(b.bidDue)))
    .slice(0, 5);

  return (
    <Panel title="Due next" icon={<CalendarBlank size={17} weight="duotone" />}>
      {due.length === 0 ? (
        <Empty>Nothing with a due date is open.</Empty>
      ) : (
        <div className="flex flex-col gap-0.5 p-3">
          {due.map((project) => {
            const days = daysUntil(project.bidDue);
            return (
              <Link
                key={project.id}
                href={`/bids/${project.code}/${project.stage}`}
                className="grid items-center gap-3 rounded-lg px-2 py-2 no-underline transition-colors hover:bg-panel-muted"
                style={{ gridTemplateColumns: "minmax(0,1fr) 74px" }}
              >
                <span className="flex min-w-0 flex-col leading-tight">
                  <span className="truncate text-[13px] font-semibold text-tx-primary">
                    {project.name}
                  </span>
                  <span className="truncate text-[11.5px] font-medium text-tx-muted">
                    {estimatorLabel(project)}
                  </span>
                </span>
                <span
                  className={cn(
                    "tnum text-right text-[12px] font-semibold",
                    days !== null && days < 0
                      ? "text-status-error"
                      : days !== null && days <= 7
                        ? "text-status-warning"
                        : "text-tx-secondary",
                  )}
                >
                  {dueLabel(days)}
                </span>
              </Link>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

export function EstimatorLoad({ projects }: { projects: Project[] }) {
  const live = projects.filter(isLive);
  const byPerson = [...groupBy(live, estimatorLabel).entries()]
    .map(([name, rows]) => ({ name, rows, total: sumValue(rows) }))
    .sort((a, b) => b.rows.length - a.rows.length);
  const busiest = Math.max(1, ...byPerson.map((person) => person.rows.length));

  return (
    <Panel title="Estimator load" icon={<UsersThree size={17} weight="duotone" />}>
      {byPerson.length === 0 ? (
        <Empty>No open bids to share out.</Empty>
      ) : (
        <div className="flex flex-col gap-1 p-3">
          {byPerson.map(({ name, rows, total }) => (
            <div
              key={name}
              className="grid items-center gap-3 rounded-lg px-2 py-2"
              style={{ gridTemplateColumns: "28px minmax(0,1fr) 72px" }}
            >
              <span className="grid h-7 w-7 place-items-center rounded-full bg-brand-soft text-[10.5px] font-bold text-brand-primary">
                {rows[0]?.estimator?.initials || "—"}
              </span>
              <span className="flex min-w-0 flex-col gap-1 leading-tight">
                <span className="flex items-baseline gap-2">
                  <span className="truncate text-[12.5px] font-medium text-tx-primary">{name}</span>
                  <span className="shrink-0 text-[11px] font-medium text-tx-muted">
                    {rows.length} open bid{rows.length === 1 ? "" : "s"}
                  </span>
                </span>
                <span className="h-1.5 overflow-hidden rounded-full bg-panel-muted">
                  <span
                    // Three or more open bids is where the prototype starts
                    // calling a desk busy.
                    className={cn(
                      "block h-full rounded-full",
                      rows.length >= 3 ? "bg-status-warning" : "bg-brand-primary",
                    )}
                    style={{ width: `${Math.round((rows.length / busiest) * 100)}%` }}
                  />
                </span>
              </span>
              <span className="tnum text-right text-[12px] font-medium text-tx-secondary">
                {formatMoneyShort(total)}
              </span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

export function BidToOrder({ projects }: { projects: Project[] }) {
  const won = projects.filter((project) => project.outcome === "won");
  const ordered = won.filter((project) => (project.p21OrderNo ?? "").trim());
  const decided = projects.filter((project) => project.outcome);
  const byPerson = [...groupBy(decided, estimatorLabel).entries()]
    .map(([name, rows]) => {
      const theirWins = rows.filter((row) => row.outcome === "won");
      return {
        name,
        initials: rows[0]?.estimator?.initials || "—",
        won: theirWins.length,
        decided: rows.length,
        pct: Math.round((theirWins.length / rows.length) * 100),
        total: sumValue(theirWins),
      };
    })
    .sort((a, b) => b.pct - a.pct);

  return (
    <Panel title="Bid to order" icon={<Receipt size={17} weight="duotone" />}>
      <div className="border-b border-subtle px-5 py-3.5">
        <div className="text-[13px] font-semibold text-tx-primary">
          {ordered.length} of {won.length} won bids raised in P21
        </div>
        <p className="mt-1 text-[11.5px] leading-relaxed text-tx-muted">
          {won.length
            ? `${Math.round((ordered.length / won.length) * 100)}% of won bids have an order number against them. Not bid jobs are excluded.`
            : "No bids have been won yet."}
        </p>
      </div>
      {byPerson.length === 0 ? (
        <Empty>No decided bids yet.</Empty>
      ) : (
        <div className="flex flex-col gap-1 p-3">
          {byPerson.map((row) => (
            <div
              key={row.name}
              className="grid items-center gap-3 rounded-lg px-2 py-2"
              style={{ gridTemplateColumns: "28px minmax(0,1fr) 46px 72px" }}
            >
              <span className="grid h-7 w-7 place-items-center rounded-full bg-panel-muted text-[10.5px] font-bold text-tx-secondary">
                {row.initials}
              </span>
              <span className="flex min-w-0 flex-col leading-tight">
                <span className="truncate text-[12.5px] font-medium text-tx-primary">
                  {row.name}
                </span>
                <span className="text-[11px] font-medium text-tx-muted">
                  {row.won} won of {row.decided} decided
                </span>
              </span>
              <span
                className={cn(
                  "tnum text-right text-[12.5px] font-bold",
                  row.pct >= 50 ? "text-status-success" : "text-status-warning",
                )}
              >
                {row.pct}%
              </span>
              <span className="tnum text-right text-[12px] font-medium text-tx-secondary">
                {formatMoneyShort(row.total)}
              </span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

export function ValueByProgramme({ projects }: { projects: Project[] }) {
  const byBrand = [...groupBy(projects, (project) => project.brand?.trim() || "Unbranded").entries()]
    .map(([brand, rows]) => ({ brand, total: sumValue(rows) }))
    .sort((a, b) => b.total - a.total);
  const biggest = Math.max(1, ...byBrand.map((row) => row.total));

  return (
    <Panel title="Value by programme" icon={<Buildings size={17} weight="duotone" />}>
      {byBrand.length === 0 ? (
        <Empty>No bids on the board.</Empty>
      ) : (
        <div className="flex flex-col gap-1 p-3">
          {byBrand.map(({ brand, total }) => (
            <Link
              key={brand}
              href={`/bids?q=${encodeURIComponent(brand === "Unbranded" ? "" : brand)}`}
              className="grid items-center gap-3 rounded-lg px-2 py-2 no-underline transition-colors hover:bg-panel-muted"
              style={{ gridTemplateColumns: "118px minmax(0,1fr) 74px" }}
            >
              <span className="truncate text-[12.5px] font-medium text-tx-primary">{brand}</span>
              <span className="h-1.5 overflow-hidden rounded-full bg-panel-muted">
                <span
                  className="block h-full rounded-full bg-brand-primary"
                  style={{ width: `${Math.round((total / biggest) * 100)}%` }}
                />
              </span>
              <span className="tnum text-right text-[12px] font-medium text-tx-secondary">
                {formatMoneyShort(total)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </Panel>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="px-5 py-8 text-center text-[12.5px] font-medium text-tx-muted">{children}</p>;
}
