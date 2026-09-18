import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import useSWR from "swr";

import { ReviewFlagsPanel } from "@/components/proposal/review-flags-panel";
import type { ReviewFlag } from "@/lib/types";

vi.mock("swr", () => ({ default: vi.fn() }));
afterEach(cleanup);

it("renders derived and agent flags, including missing fields, most severe first", () => {
  const flags: ReviewFlag[] = [
    { opening: "Door 3", field: "fire_rating", severity: "high", note: "Missing rating", source_page: 16 },
    { opening_id: "Mark 4", category: "cost_entry_required", severity: "critical", issue: "Verify before pricing" },
    { opening: null, field: null, severity: "low", action_required: "Review the schedule" },
  ];
  vi.mocked(useSWR).mockReturnValue({ data: { flags }, isLoading: false, isValidating: false, error: undefined, mutate: vi.fn() });

  render(<ReviewFlagsPanel code="CBC-260006" />);

  expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("Mark 4");
  expect(screen.getByRole("alert")).toHaveTextContent("Verify before pricing");
  expect(screen.getByText("cost entry required")).toBeInTheDocument();
  expect(screen.getByText("Verify before pricing")).toBeInTheDocument();
  expect(screen.getByText("fire rating")).toBeInTheDocument();
  expect(screen.getByText("Missing rating · sheet page 16")).toBeInTheDocument();
  expect(screen.getByText("General review")).toBeInTheDocument();
  expect(screen.getByText("Review the schedule")).toBeInTheDocument();
});
