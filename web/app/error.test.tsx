import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { refresh } = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

const { default: ErrorPage } = await import("./error");

describe("error page", () => {
  it("retries by re-running the server render, not just the boundary", () => {
    const reset = vi.fn();
    render(<ErrorPage error={new Error("503")} reset={reset} />);
    expect(screen.getByRole("alert").textContent).toContain("temporarily unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refresh).toHaveBeenCalledOnce();
    expect(reset).toHaveBeenCalledOnce();
  });
});
