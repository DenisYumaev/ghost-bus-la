import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { CANCELLATIONS, RATES, SUPPRESSED } from "@/tests/fixtures";
import { answer } from "@/tests/routes";

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/api/client", async (original) => ({
  ...(await original<typeof import("@/lib/api/client")>()),
  apiGet,
}));

const { default: Home } = await import("./page");
const { default: LinesPage } = await import("./lines/page");
const { default: MethodPage } = await import("./method/page");
const { default: StatusPage } = await import("./status/page");

const LINES = {
  window: "28d", window_start: "2026-11-04", data_through: "2026-12-01",
  data_as_of: "2026-12-01T17:40:12Z",
  lines: [
    { line: "2", line_slug: "2", display_name: "2", line_kind: "Metro Local Line", summary: { ...RATES, missed_rate: 0.03 } },
    { line: "10/48", line_slug: "10-48", display_name: "10/48", line_kind: null, summary: SUPPRESSED },
    { line: "720", line_slug: "720", display_name: "720", line_kind: "Metro Rapid Line", summary: { ...RATES, missed_rate: 0.08 } },
  ],
}; // prettier-ignore

const METHOD = {
  data_as_of: "2026-12-01T17:40:12Z",
  thresholds: [{ name: "min_cell_trips", value: "30", unit: "trips", description: "Fewest trips behind any published rate.", decision: "ADR-025, ADR-026" }],
  outcomes: [{ term: "missed", meaning: "Not seen while the feeds were healthy." }],
  rates: [{ term: "missed_rate", meaning: "Missed trips divided by scheduled trips minus unknown ones (n_trips)." }],
  notes: ["Ghost Bus LA is not affiliated with LA Metro."],
}; // prettier-ignore

const bucket = (feed: string, healthy: boolean) => ({
  feed, bucket_start: "2026-12-01T20:00:00Z", n_fetches: 10, n_success: healthy ? 10 : 0,
  n_errors: healthy ? 0 : 10, error_rate: healthy ? 0 : 1, freshest_age_s: 3, healthy,
}); // prettier-ignore

const isLinePage = (href: string | null) => href !== null && /^\/lines\/[^?]/.test(href);

beforeEach(() => {
  apiGet.mockReset();
  // Pinned so the fixtures' data_as_of (2026-12-01T17:40Z) is fresh unless a test moves the clock.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-12-01T18:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
});

describe("home", () => {
  it("counts trips listed as canceled with the feed time, never 'right now'", async () => {
    answer(apiGet, { "/v1/cancellations/current": CANCELLATIONS });
    render(await Home());
    expect(
      screen.getByText("As of 9:38 AM, Metro's realtime feed listed 1 trip as canceled."),
    ).toBeTruthy();
    expect(screen.getByText("This can be up to about an hour behind the feed.")).toBeTruthy();
    expect(screen.getByRole("search").getAttribute("action")).toBe("/lines");
  });

  it("never presents a stale list as a count", async () => {
    answer(apiGet, { "/v1/cancellations/current": { ...CANCELLATIONS, stale: true } });
    render(await Home());
    expect(screen.getByRole("status").textContent).toContain("may be out of date");
    expect(screen.queryByText(/listed .* as canceled/)).toBeNull();
  });

  it("says unavailable when the API answers 503", async () => {
    answer(apiGet, { "/v1/cancellations/current": new ApiError(503, "No published data yet") });
    render(await Home());
    expect(screen.getByRole("status").textContent).toBe(
      "Current cancellations are unavailable right now.",
    );
  });

  it("keeps the page and its search when the API is unreachable", async () => {
    answer(apiGet, { "/v1/cancellations/current": new TypeError("fetch failed") });
    render(await Home());
    expect(screen.getByRole("search")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe(
      "Current cancellations are unavailable right now.",
    );
  });
});

describe("all lines", () => {
  const page = async (params: { q?: string; sort?: string }) =>
    render(await LinesPage({ searchParams: Promise.resolve(params) }));

  it("lists every line with its rate and range, or not enough data", async () => {
    answer(apiGet, { "/v1/lines": LINES });
    await page({});
    const links = screen.getAllByRole("link").filter((a) => isLinePage(a.getAttribute("href")));
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/lines/2",
      "/lines/10-48",
      "/lines/720",
    ]);
    expect(within(links[0]!).getByText("3% never ran")).toBeTruthy();
    expect(within(links[0]!).getByText("range 4 to 6%")).toBeTruthy();
    // A line tracked for fewer than 28 days says how many.
    expect(within(links[0]!).getByText("over 17 days")).toBeTruthy();
    expect(within(links[1]!).getByText("not enough data")).toBeTruthy();
    expect(screen.getByText(/in the 28 days through Dec 1/)).toBeTruthy();
    expect(screen.queryByText(/may be out of date/)).toBeNull();
  });

  it("sorts least reliable first", async () => {
    answer(apiGet, { "/v1/lines": LINES });
    await page({ sort: "reliability" });
    const hrefs = screen
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"))
      .filter(isLinePage);
    expect(hrefs).toEqual(["/lines/720", "/lines/2", "/lines/10-48"]);
    expect(
      screen.getByRole("link", { name: "Least reliable first" }).getAttribute("aria-current"),
    ).toBe("true");
  });

  it("filters by number and says so when nothing matches", async () => {
    answer(apiGet, { "/v1/lines": LINES });
    await page({ q: "999" });
    expect(screen.getByText("No line matches “999”.")).toBeTruthy();
  });

  it("says when nothing is published, without an empty quote", async () => {
    answer(apiGet, { "/v1/lines": { ...LINES, lines: [] } });
    await page({});
    expect(screen.getByText("No lines are published yet.")).toBeTruthy();
  });

  it("counts one line in the singular", async () => {
    answer(apiGet, { "/v1/lines": LINES });
    await page({ q: "720" });
    expect(screen.getByText("1 line")).toBeTruthy();
  });

  it("lets an API outage reach the error page", async () => {
    answer(apiGet, { "/v1/lines": new ApiError(503, "Database unavailable") });
    await expect(LinesPage({ searchParams: Promise.resolve({}) })).rejects.toThrow("503");
  });

  it("warns when the data is over an hour old", async () => {
    vi.setSystemTime(new Date("2026-12-01T19:00:00Z"));
    answer(apiGet, { "/v1/lines": LINES });
    await page({});
    expect(screen.getByRole("status").textContent).toContain("may be out of date");
  });
});

describe("method", () => {
  it("shows definitions, thresholds and notes from the build", async () => {
    answer(apiGet, { "/v1/meta/method": METHOD });
    render(await MethodPage());
    expect(screen.getByText("Not seen while the feeds were healthy.")).toBeTruthy();
    expect(screen.getByRole("row", { name: /min_cell_trips 30 trips/ })).toBeTruthy();
    expect(screen.getByText("Ghost Bus LA is not affiliated with LA Metro.")).toBeTruthy();
    expect(screen.queryByText(/may be out of date/)).toBeNull();
  });

  it("warns when the build is over an hour old", async () => {
    vi.setSystemTime(new Date("2026-12-01T19:00:00Z"));
    answer(apiGet, { "/v1/meta/method": METHOD });
    render(await MethodPage());
    expect(screen.getByRole("status").textContent).toContain("may be out of date");
  });
});

describe("status", () => {
  it("shows each day's captured share per feed and the last publish", async () => {
    answer(apiGet, {
      "/v1/system/feed-health": {
        hours: 168,
        data_as_of: "2026-12-01T17:40:12Z",
        buckets: [bucket("vehicle_positions", true), bucket("trip_updates", false)],
      },
    });
    render(await StatusPage());
    expect(screen.getByText("Numbers last published Tue, Dec 1 at 9:40 AM.")).toBeTruthy();
    const row = screen.getByRole("row", { name: /Tue, Dec 1/ });
    expect(
      within(row)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["100% captured", "0% captured"]);
    // One bucket is far from a full day.
    expect(row.textContent).toContain("(partial day)");
    expect(screen.queryByText(/may be out of date/)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith("/v1/system/feed-health", {
      query: { hours: 168 },
      revalidate: 60,
    });
  });

  it("says so when nothing is published, and warns when the publish is old", async () => {
    vi.setSystemTime(new Date("2026-12-03T00:00:00Z"));
    answer(apiGet, {
      "/v1/system/feed-health": { hours: 168, data_as_of: "2026-12-01T17:40:12Z", buckets: [] },
    });
    render(await StatusPage());
    expect(screen.getByText("No feed data is published yet.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("may be out of date");
  });
});
