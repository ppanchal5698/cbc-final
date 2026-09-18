import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { Header } from "@/components/shell/header";
import { UiStateProvider, useUiState } from "@/components/shell/ui-state";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

beforeEach(() => {
  localStorage.clear();
});

vi.mock("next/navigation", () => ({
  usePathname: () => "/bids",
}));

vi.mock("next-auth/react", () => ({
  signOut: vi.fn(),
}));

vi.mock("@/lib/proxy-fetcher", () => ({
  proxyFetcher: vi.fn().mockResolvedValue({ count: 0 }),
}));

function SidebarStatusIndicator() {
  const { sidebarCollapsed } = useUiState();
  return <div data-testid="sidebar-state">{sidebarCollapsed ? "collapsed" : "expanded"}</div>;
}

describe("Header (Sidebar Toggle)", () => {
  const user = { name: "Admin", initials: "AD", role: "admin" };

  it("renders sidebar toggle button and toggles state", () => {
    render(
      <UiStateProvider>
        <Header crumbs={[{ label: "Bids", href: "/bids" }]} user={user} />
        <SidebarStatusIndicator />
      </UiStateProvider>
    );

    const toggleBtn = screen.getByRole("button", { name: "Collapse sidebar" });
    expect(toggleBtn).toBeInTheDocument();
    expect(screen.getByTestId("sidebar-state")).toHaveTextContent("expanded");

    fireEvent.click(toggleBtn);

    expect(screen.getByTestId("sidebar-state")).toHaveTextContent("collapsed");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(screen.getByTestId("sidebar-state")).toHaveTextContent("expanded");
  });
});
