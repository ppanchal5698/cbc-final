/**
 * What the board and the dashboard say about a bid.
 *
 * One implementation of "what state is this bid in" and of the roll-ups drawn
 * from it, so the board's chips and the dashboard's panels can never disagree.
 * Everything here is derived from the `Project` rows the API already returns.
 */
import type { Project } from "@/lib/types";

export type BoardStatus =
  | "Intake"
  | "Extracting"
  | "Review"
  | "In progress"
  | "Sent"
  | "Closed"
  | "Shelved";

/** In source order: the pipeline panel draws them left to right like this. */
export const PIPELINE_STAGES: BoardStatus[] = [
  "Intake",
  "Extracting",
  "Review",
  "In progress",
  "Sent",
];

const WORKING = new Set(["extracting", "pricing", "quoting"]);

/**
 * The single state an estimator would name for this bid.
 *
 * Order matters: a shelved or decided bid is that whatever else is true of it,
 * and a live Claude pass outranks a stale flag count.
 */
export function boardStatus(project: Project): BoardStatus {
  if (project.bidStatus === "not_bid") return "Shelved";
  if (project.outcome) return "Closed";
  if (project.handedOffTo) return "Sent";
  if (project.activeJob || (project.chainState && WORKING.has(project.chainState)))
    return "Extracting";
  if ((project.counts?.needsLook ?? 0) > 0) return "Review";
  if (project.stage === "intake") return "Intake";
  return "In progress";
}

/** Bid, not decided, not shelved — the work actually in front of the team. */
export function isLive(project: Project): boolean {
  return project.bidStatus !== "not_bid" && !project.outcome;
}

export function outcomeCounts(projects: Project[]) {
  const won = projects.filter((p) => p.outcome === "won").length;
  const lost = projects.filter((p) => p.outcome === "lost").length;
  const notBid = projects.filter((p) => p.bidStatus === "not_bid").length;
  const decided = won + lost;
  return {
    won,
    lost,
    notBid,
    decided,
    open: projects.filter(isLive).length,
    /** Not-bid jobs are deliberately absent from the denominator. */
    winRate: decided ? Math.round((won / decided) * 100) : null,
  };
}

export function value(project: Project): number {
  return project.quoteTotal ?? 0;
}

/** Sum a numeric field over rows, so the panels never repeat a reduce. */
export function sumValue(projects: Project[]): number {
  return projects.reduce((total, project) => total + value(project), 0);
}

/** Whole days from today to a due date; negative is overdue. */
export function daysUntil(due?: string | null): number | null {
  if (!due) return null;
  const then = new Date(due);
  if (Number.isNaN(then.getTime())) return null;
  const startOfDay = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  return Math.round((startOfDay(then) - startOfDay(new Date())) / 86_400_000);
}

export function dueLabel(days: number | null): string {
  if (days === null) return "no due date";
  if (days < 0) return `${Math.abs(days)} days over`;
  if (days === 0) return "Today";
  return `${days} day${days === 1 ? "" : "s"}`;
}

/** Group rows by a key, keeping first-seen order. */
export function groupBy<T>(rows: T[], key: (row: T) => string): Map<string, T[]> {
  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const k = key(row);
    const bucket = groups.get(k);
    if (bucket) bucket.push(row);
    else groups.set(k, [row]);
  }
  return groups;
}

/** How a bid's assigned estimator should read on screen. */
export function estimatorLabel(project: Project): string {
  return project.estimator?.name ?? (project.assignedEstimator || "Unassigned");
}
