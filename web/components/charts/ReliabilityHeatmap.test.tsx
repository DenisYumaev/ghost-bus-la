import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { cell } from "@/tests/fixtures";
import { ReliabilityHeatmap, cellLabel, stepFor } from "./ReliabilityHeatmap";

describe("cell labels (color is never the only signal)", () => {
  it("states the rate, trips and range", () => {
    expect(cellLabel("weekday", 17, cell({}))).toBe(
      "Weekdays, 5 PM: 5% of 412 trips never ran, range 4 to 7%",
    );
  });

  it("says not enough data for a suppressed cell, never a zero", () => {
    const label = cellLabel(
      "sunday",
      6,
      cell({ suppressed: true, missed_rate: null, n_trips: 12 }),
    );
    expect(label).toBe("Sundays, 6 AM: not enough data (12 trips)");
  });

  it("says no scheduled trips where there are none", () => {
    expect(cellLabel("saturday", 3, undefined)).toBe("Saturdays, 3 AM: no scheduled trips");
  });

  it("leaves the range out when there is none", () => {
    expect(cellLabel("weekday", 9, cell({ hour_local: 9, ci_low: null, ci_high: null }))).toBe(
      "Weekdays, 9 AM: 5% of 412 trips never ran",
    );
  });
});

describe("color steps", () => {
  it("bins rates at 2, 5, 10 and 20%", () => {
    expect([0, 0.019, 0.02, 0.049, 0.05, 0.1, 0.2, 1].map(stepFor)).toEqual([
      0, 0, 1, 1, 2, 3, 4, 4,
    ]);
  });
});

describe("ReliabilityHeatmap", () => {
  const cells = [
    cell({}),
    cell({ day_type: "sunday", hour_local: 6, suppressed: true, missed_rate: null, n_trips: 12 }),
  ];

  it("draws 72 cells, focusable only where there are trips", () => {
    const { container } = render(<ReliabilityHeatmap cells={cells} id="d0" />);
    const rects = container.querySelectorAll("rect[data-state]");
    expect(rects).toHaveLength(72);
    expect(container.querySelectorAll('rect[tabindex="0"]')).toHaveLength(2);
  });

  it("hatches suppressed cells", () => {
    render(<ReliabilityHeatmap cells={cells} id="d0" />);
    const suppressed = screen.getByRole("img", {
      name: "Sundays, 6 AM: not enough data (12 trips)",
    });
    expect(suppressed.getAttribute("fill")).toBe("url(#d0-hatch)");
    expect(suppressed.dataset.state).toBe("suppressed");
  });

  it("repeats every cell in a table view", () => {
    render(<ReliabilityHeatmap cells={cells} id="d0" />);
    const table = screen.getByRole("table");
    const fivePm = within(table).getByRole("row", { name: /^5 PM/ });
    expect(
      within(fivePm)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["5% of 412", "–", "–"]);
    const sixAm = within(table).getByRole("row", { name: /^6 AM/ });
    expect(within(sixAm).getAllByRole("cell")[2]?.textContent).toBe("Not enough data");
  });
});
