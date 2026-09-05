import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { BoardGroups } from "@/components/bids/board-groups";
import type { Project } from "@/lib/types";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

function sampleProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "1",
    code: "bid_01",
    slug: "bid-01",
    name: "Test Tower",
    brand: "Acme",
    stage: "intake",
    progress: 0,
    counts: { total: 0, clear: 0, needsLook: 0, duplicate: 0, byHand: 0 },
    documentCount: 0,
    createdAt: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("BoardGroups", () => {
  it("groups projects by brand", () => {
    render(
      <BoardGroups
        projects={[
          sampleProject({ id: "1", brand: "Acme", code: "bid_01" }),
          sampleProject({ id: "2", brand: "Acme", code: "bid_02" }),
          sampleProject({ id: "3", brand: "Beta", code: "bid_03" }),
        ]}
      />,
    );

    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("bid_01")).toBeInTheDocument();
    expect(screen.getByText("bid_02")).toBeInTheDocument();
    expect(screen.getByText("bid_03")).toBeInTheDocument();
  });
});
