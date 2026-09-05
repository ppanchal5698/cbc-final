import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { BidBoardSearch } from "@/components/bids/bid-board-search";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

describe("BidBoardSearch", () => {
  beforeEach(() => {
    replace.mockReset();
  });

  it("debounces URL updates when typing", async () => {
    const user = userEvent.setup();
    render(<BidBoardSearch stage="intake" initialQuery="" />);

    const input = screen.getByRole("searchbox", { name: /search bids/i });
    await user.type(input, "tower");

    await waitFor(
      () => {
        expect(replace).toHaveBeenCalledWith("/bids?stage=intake&q=tower");
      },
      { timeout: 2000 },
    );
  });
});
