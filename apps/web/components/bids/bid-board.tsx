"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { BoardGroups } from "@/components/bids/board-groups";
import { BidStateDialog } from "@/components/bids/bid-state-dialog";
import { PlansDialog } from "@/components/bids/plans-dialog";
import { BID_STATUS_LABEL, OUTCOME_LABEL, patchBid } from "@/components/bids/bid-state";
import { boardStatus, estimatorLabel, isLive, outcomeCounts, value } from "@/lib/board";
import type { BidStatus, Outcome, Project } from "@/lib/types";
import { cn } from "@/lib/utils";

type Filter = "All" | "Mine" | "In flight" | "Sent" | "Won" | "Lost" | "Not bid";
type Sort = "due" | "entered" | "value";

const FILTERS: Filter[] = ["All", "Mine", "In flight", "Sent", "Won", "Lost", "Not bid"];
const SORTS: { key: Sort; label: string }[] = [
  { key: "due", label: "Due date" },
  { key: "entered", label: "Date entered" },
  { key: "value", label: "Value" },
];

const IN_FLIGHT = new Set(["Intake", "Extracting", "Review", "In progress"]);

function matches(project: Project, filter: Filter, me: string): boolean {
  switch (filter) {
    case "Mine":
      return (project.assignedEstimator ?? "") === me.toLowerCase();
    case "In flight":
      return isLive(project) && IN_FLIGHT.has(boardStatus(project));
    case "Sent":
      return boardStatus(project) === "Sent";
    case "Won":
      return project.outcome === "won";
    case "Lost":
      return project.outcome === "lost";
    case "Not bid":
      return project.bidStatus === "not_bid";
    default:
      return true;
  }
}

function Chip({
  label,
  count,
  on,
  onClick,
  title,
}: {
  label: string;
  count?: number;
  on: boolean;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      aria-pressed={on}
      className={cn(
        "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12.5px] font-semibold shadow-1 transition-colors",
        on
          ? "border-tx-primary bg-tx-primary text-background"
          : "border-subtle bg-panel text-tx-secondary hover:bg-panel-muted hover:text-tx-primary",
      )}
    >
      {label}
      {count !== undefined && (
        <span className={cn("tnum text-[11px]", on ? "opacity-60" : "text-tx-muted")}>{count}</span>
      )}
    </button>
  );
}

/**
 * The bid board: what is open, who owns it, and how each one ended.
 *
 * Filtering and sorting stay on the client. The page already loads the whole
 * board in one request - a desk runs tens of live bids, not thousands - so a
 * chip is instant and does not put the filter in the URL where it would have
 * to be parsed back out again. The search box is the exception: it is a server
 * query because it has to reach bids this page did not load.
 */
export function BidBoard({ projects, me }: { projects: Project[]; me: string }) {
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>("All");
  const [estimator, setEstimator] = useState<string>("All");
  const [sort, setSort] = useState<Sort>("due");
  const [editing, setEditing] = useState<Project | null>(null);
  const [plansFor, setPlansFor] = useState<Project | null>(null);

  const stats = outcomeCounts(projects);

  const estimators = useMemo(() => {
    const seen = new Map<string, string>();
    for (const project of projects) {
      if (project.assignedEstimator) seen.set(project.assignedEstimator, estimatorLabel(project));
    }
    return [...seen.entries()];
  }, [projects]);

  const rows = useMemo(() => {
    const filtered = projects.filter(
      (project) =>
        matches(project, filter, me) &&
        (estimator === "All" || (project.assignedEstimator ?? "") === estimator),
    );
    return [...filtered].sort((a, b) => {
      if (sort === "value") return value(b) - value(a);
      if (sort === "entered") return b.createdAt.localeCompare(a.createdAt);
      // Due date: no date sorts last rather than first, which is what an empty
      // string would do.
      return (a.bidDue ?? "9999").localeCompare(b.bidDue ?? "9999");
    });
  }, [projects, filter, estimator, sort, me]);

  function refresh() {
    router.refresh();
  }

  async function setBidStatus(project: Project, next: BidStatus) {
    await patchBid(project, { bidStatus: next }, () => {
      toast.success(`Marked ${BID_STATUS_LABEL[next]}`, {
        description: next === "not_bid" ? "Never counted as lost" : project.code,
      });
      refresh();
    });
  }

  async function setOutcome(project: Project, next: Outcome) {
    await patchBid(project, { outcome: next }, () => {
      toast.success(next ? OUTCOME_LABEL[next] : "Outcome cleared", {
        description: next ? project.code : "Back to open",
      });
      refresh();
    });
  }

  return (
    <>
      <div className="mb-5 flex flex-wrap items-center gap-6 rounded-xl border border-subtle bg-panel px-5 py-3.5 shadow-1">
        {[
          { label: "Open", value: String(stats.open), tone: "text-brand-primary" },
          { label: "Won", value: String(stats.won), tone: "text-status-success" },
          { label: "Lost", value: String(stats.lost), tone: "text-status-error" },
          { label: "Not bid", value: String(stats.notBid), tone: "text-tx-secondary" },
          {
            label: "Win rate",
            value: stats.winRate === null ? "—" : `${stats.winRate}%`,
            tone: "text-tx-primary",
          },
        ].map((stat) => (
          <span key={stat.label} className="flex flex-col leading-tight">
            <span className="text-[10px] font-bold uppercase tracking-widest text-tx-muted">
              {stat.label}
            </span>
            <span className={cn("tnum mt-0.5 text-[18px] font-bold", stat.tone)}>{stat.value}</span>
          </span>
        ))}
        <span className="flex-1" />
        <span className="text-[11.5px] font-medium text-tx-muted">
          Click a bid status or outcome chip to change it
        </span>
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        {FILTERS.map((option) => (
          <Chip
            key={option}
            label={option}
            count={projects.filter((project) => matches(project, option, me)).length}
            on={filter === option}
            onClick={() => setFilter(option)}
          />
        ))}
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
          Estimator
        </span>
        <Chip
          label="All"
          count={projects.length}
          on={estimator === "All"}
          onClick={() => setEstimator("All")}
        />
        {estimators.map(([email, name]) => (
          <Chip
            key={email}
            label={name}
            title={email}
            count={projects.filter((project) => project.assignedEstimator === email).length}
            on={estimator === email}
            onClick={() => setEstimator(email)}
          />
        ))}
        <span className="flex-1" />
        <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">Sort</span>
        {SORTS.map((option) => (
          <Chip
            key={option.key}
            label={option.label}
            on={sort === option.key}
            onClick={() => setSort(option.key)}
          />
        ))}
      </div>

      <BoardGroups
        projects={rows}
        onSetBidStatus={setBidStatus}
        onSetOutcome={setOutcome}
        onEdit={setEditing}
        onPlans={setPlansFor}
      />

      <BidStateDialog
        project={editing}
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        onSaved={refresh}
      />
      <PlansDialog
        project={plansFor}
        open={plansFor !== null}
        onOpenChange={(open) => !open && setPlansFor(null)}
      />
    </>
  );
}
