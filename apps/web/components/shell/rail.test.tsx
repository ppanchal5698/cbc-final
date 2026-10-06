import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { Rail } from "@/components/shell/rail";
import { UiStateProvider } from "@/components/shell/ui-state";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

beforeEach(() => {
  localStorage.clear();
});

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

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

describe("Rail (Collapsible Sidebar)", () => {
  const user = { name: "Admin", initials: "AD" };

  it("renders in expanded state by default", () => {
    render(
      <UiStateProvider>
        <Rail staleBooks={3} deadJobs={2} user={user} />
      </UiStateProvider>
    );

    expect(screen.getByText("OPS·HUB")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Bid board")).toBeInTheDocument();
    expect(screen.getByText("Dead letter")).toBeInTheDocument();
    expect(screen.getByText("Price books")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByText("Focus mode")).toBeInTheDocument();

    // Badges in expanded state
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    expect(nav.className).toContain("w-[216px]");
  });

  it("collapses when clicking the collapse button", () => {
    render(
      <UiStateProvider>
        <Rail staleBooks={3} deadJobs={2} user={user} />
      </UiStateProvider>
    );

    const collapseBtns = screen.getAllByRole("button", { name: "Collapse sidebar" });
    fireEvent.click(collapseBtns[0]);

    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    expect(nav.className).toContain("w-[64px]");

    // Text labels should not be in the DOM when collapsed
    expect(screen.queryByText("OPS·HUB")).not.toBeInTheDocument();
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();

    // Expand button should now be available
    const expandBtns = screen.getAllByRole("button", { name: "Expand sidebar" });
    expect(expandBtns.length).toBeGreaterThan(0);

    // Badges should still be visible in collapsed mode
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("expands back when clicking the expand button", () => {
    render(
      <UiStateProvider>
        <Rail staleBooks={0} deadJobs={0} user={user} />
      </UiStateProvider>
    );

    const collapseBtns = screen.getAllByRole("button", { name: "Collapse sidebar" });
    fireEvent.click(collapseBtns[0]);

    const expandBtns = screen.getAllByRole("button", { name: "Expand sidebar" });
    fireEvent.click(expandBtns[0]);

    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    expect(nav.className).toContain("w-[216px]");
    expect(screen.getByText("OPS·HUB")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("toggles sidebar with Ctrl+B shortcut", () => {
    render(
      <UiStateProvider>
        <Rail staleBooks={0} deadJobs={0} user={user} />
      </UiStateProvider>
    );

    const nav = screen.getByRole("navigation", { name: "Main Navigation" });
    expect(nav.className).toContain("w-[216px]");

    fireEvent.keyDown(window, { key: "b", ctrlKey: true });
    expect(nav.className).toContain("w-[64px]");

    fireEvent.keyDown(window, { key: "b", ctrlKey: true });
    expect(nav.className).toContain("w-[216px]");
  });

  it("persists collapsed preference in localStorage", () => {
    render(
      <UiStateProvider>
        <Rail staleBooks={0} deadJobs={0} user={user} />
      </UiStateProvider>
    );

    const collapseBtns = screen.getAllByRole("button", { name: "Collapse sidebar" });
    fireEvent.click(collapseBtns[0]);

    expect(localStorage.getItem("opshub-sidebar-collapsed")).toBe("1");

    const expandBtns = screen.getAllByRole("button", { name: "Expand sidebar" });
    fireEvent.click(expandBtns[0]);

    expect(localStorage.getItem("opshub-sidebar-collapsed")).toBe("0");
  });

  it("shows the administration pages to an admin only", () => {
    const { unmount } = render(
      <UiStateProvider>
        <Rail staleBooks={0} deadJobs={0} user={{ ...user, role: "admin" }} />
      </UiStateProvider>
    );
    for (const [label, href] of [
      ["Pricing", "/pricing"],
      ["Reference data", "/reference-data"],
      ["Users", "/users"],
      ["Audit log", "/audit"],
    ]) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
    expect(screen.getByText("Administration")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
    unmount();

    render(
      <UiStateProvider>
        <Rail staleBooks={0} deadJobs={0} user={{ ...user, role: "estimator" }} />
      </UiStateProvider>
    );
    expect(screen.queryByRole("link", { name: "Pricing" })).toBeNull();
    expect(screen.queryByText("Administration")).toBeNull();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });
});
