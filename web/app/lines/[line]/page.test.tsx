import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { CANCELLATIONS, DETAIL, SUPPRESSED, cell } from "@/tests/fixtures";

const { apiGet, notFound } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  apiGet,
}));
vi.mock("next/navigation", () => ({ notFound }));

const { default: LinePage, generateMetadata } = await import("./page");
const props = { params: Promise.resolve({ line: "720" }) };

function answer(routes: Record<string, unknown>) {
  apiGet.mockImplementation(
    async (path: string, options?: { query?: { direction_id?: number } }) => {
      const id = options?.query?.direction_id;
      const value = routes[id !== undefined ? `${path}#${id}` : path];
      if (value instanceof Error) throw value;
      if (value === undefined) throw new Error(`unexpected ${path}`);
      return value;
    },
  );
}

const GRID = { cells: [cell({})] };
const ALL = {
  "/v1/lines/{line}": DETAIL,
  "/v1/lines/{line}/reliability#0": GRID,
  "/v1/lines/{line}/reliability#1": GRID,
  "/v1/cancellations/current": CANCELLATIONS,
};

describe("line page", () => {
  // A block body: a function returned from beforeEach would run as its teardown.
  beforeEach(() => {
    apiGet.mockReset();
    notFound.mockClear();
    // Pinned: data_as_of is 2026-12-01T17:40Z, so the page's data is fresh (no stale notice).
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-12-01T18:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("answers first, lists cancellations, and draws each direction", async () => {
    answer(ALL);
    render(await LinePage(props));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Line 720");
    expect(
      screen.getByText("Over the 17 days tracked so far, 5% of line 720's trips never ran."),
    ).toBeTruthy();
    expect(screen.getByText("10:30 AM toward Santa Monica")).toBeTruthy();
    expect(screen.queryByText(/may be out of date/)).toBeNull();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Announced cancellations right now",
      "Toward Santa Monica",
      "Toward Commerce",
    ]);
    expect(screen.getAllByRole("table")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "How we count" }).getAttribute("href")).toBe("/method");
  });

  it("asks for cancellations with a 60-second revalidate", async () => {
    answer(ALL);
    await LinePage(props);
    expect(apiGet).toHaveBeenCalledWith("/v1/cancellations/current", {
      query: { line: "720" },
      revalidate: 60,
    });
  });

  it("keeps the page when one direction or the cancellations aren't available", async () => {
    answer({
      ...ALL,
      "/v1/lines/{line}/reliability#1": new ApiError(404, "Direction not found"),
      "/v1/cancellations/current": new ApiError(503, "No published data yet"),
    });
    render(await LinePage(props));
    expect(screen.getByText("No hour-by-hour data for this direction yet.")).toBeTruthy();
    // Never an empty section that looks like a quiet day (ADR-029).
    expect(screen.getByText("Current cancellations are unavailable right now.")).toBeTruthy();
    expect(screen.queryByText("No announced cancellations for this line right now.")).toBeNull();
  });

  it("is a 404 for an unknown line", async () => {
    answer({ "/v1/lines/{line}": new ApiError(404, "Line not found") });
    await expect(LinePage(props)).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("sends a database outage to the error page, never to not-found", async () => {
    answer({ "/v1/lines/{line}": new ApiError(503, "Database unavailable") });
    await expect(LinePage(props)).rejects.toThrow("503 Database unavailable");
    await expect(generateMetadata(props)).rejects.toThrow("503 Database unavailable");
    expect(notFound).not.toHaveBeenCalled();
  });

  it("lets other failures reach the error page", async () => {
    answer({ "/v1/lines/{line}": new TypeError("fetch failed") });
    await expect(LinePage(props)).rejects.toThrow("fetch failed");
  });

  it("puts the headline number in the search description", async () => {
    answer({ "/v1/lines/{line}": DETAIL });
    expect(await generateMetadata(props)).toEqual({
      title: "Is the 720 bus reliable?",
      description: "Over the 17 days tracked so far, 5% of line 720's trips never ran.",
    });
  });

  it("never puts 'not enough data' inside the headline sentence", async () => {
    answer({ "/v1/lines/{line}": { ...DETAIL, summary: { ...SUPPRESSED, suppressed: false } } });
    expect((await generateMetadata(props)).description).toBe(
      "How often LA Metro line 720 trips never ran, by hour and day of the week. An independent project, not affiliated with LA Metro.",
    );
  });
});
