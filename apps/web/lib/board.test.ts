import { describe, expect, it } from "vitest";

import { boardStatus, daysUntil, dueLabel, isLive, outcomeCounts } from "@/lib/board";
import type { Project } from "@/lib/types";

/** The handful of fields the board derivations actually read. */
function bid(overrides: Partial<Project> = {}): Project {
  return {
    id: "1",
    code: "CBC-260001",
    slug: "one",
    name: "A bid",
    stage: "extraction",
    progress: 33,
    counts: { total: 0, clear: 0, needsLook: 0, duplicate: 0, byHand: 0 },
    documentCount: 1,
    createdAt: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("boardStatus", () => {
  it("calls a shelved bid Shelved whatever else is true of it", () => {
    expect(
      boardStatus(bid({ bidStatus: "not_bid", activeJob: { id: "j" } as Project["activeJob"] })),
    ).toBe("Shelved");
  });

  it("calls a decided bid Closed even once it was handed off", () => {
    expect(boardStatus(bid({ outcome: "won", handedOffTo: "sales" }))).toBe("Closed");
  });

  it("reports a live run ahead of a stale flag count", () => {
    expect(
      boardStatus(
        bid({
          activeJob: { id: "j" } as Project["activeJob"],
          counts: { total: 3, clear: 0, needsLook: 3, duplicate: 0, byHand: 0 },
        }),
      ),
    ).toBe("Extracting");
  });

  it("reports flagged lines when nothing is running", () => {
    expect(
      boardStatus(bid({ counts: { total: 3, clear: 0, needsLook: 3, duplicate: 0, byHand: 0 } })),
    ).toBe("Review");
  });

  it("falls back to the stage", () => {
    expect(boardStatus(bid({ stage: "intake" }))).toBe("Intake");
    expect(boardStatus(bid({ stage: "quote" }))).toBe("In progress");
  });
});

describe("outcomeCounts", () => {
  const board = [
    bid({ id: "a", outcome: "won" }),
    bid({ id: "b", outcome: "won" }),
    bid({ id: "c", outcome: "lost" }),
    bid({ id: "d", bidStatus: "not_bid" }),
    bid({ id: "e" }),
  ];

  it("keeps not-bid jobs out of the win rate entirely", () => {
    const counts = outcomeCounts(board);
    expect(counts).toMatchObject({ won: 2, lost: 1, notBid: 1, decided: 3 });
    // 2 of 3 decided - the shelved job is in neither the numerator nor the
    // denominator, which is the whole point of holding it apart.
    expect(counts.winRate).toBe(67);
  });

  it("counts only undecided, un-shelved bids as open", () => {
    expect(outcomeCounts(board).open).toBe(1);
  });

  it("reports no win rate rather than 0% when nothing is decided", () => {
    expect(outcomeCounts([bid()]).winRate).toBeNull();
  });
});

describe("isLive", () => {
  it("excludes shelved and decided bids", () => {
    expect(isLive(bid())).toBe(true);
    expect(isLive(bid({ outcome: "lost" }))).toBe(false);
    expect(isLive(bid({ bidStatus: "not_bid" }))).toBe(false);
  });
});

describe("daysUntil / dueLabel", () => {
  it("counts whole days and says when a bid is overdue", () => {
    const inThreeDays = new Date(Date.now() + 3 * 86_400_000).toISOString();
    expect(daysUntil(inThreeDays)).toBe(3);
    expect(dueLabel(3)).toBe("3 days");
    expect(dueLabel(1)).toBe("1 day");
    expect(dueLabel(0)).toBe("Today");
    expect(dueLabel(-2)).toBe("2 days over");
  });

  it("has no opinion about a missing or unparseable date", () => {
    expect(daysUntil(null)).toBeNull();
    expect(daysUntil("not a date")).toBeNull();
    expect(dueLabel(null)).toBe("no due date");
  });
});
