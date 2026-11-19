import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RATES, SUPPRESSED } from "@/tests/fixtures";
import { LineSummary } from "./LineSummary";

describe("LineSummary", () => {
  it("answers first, then the range and the counts behind it", () => {
    render(<LineSummary name="720" rates={RATES} />);
    // The fixture covers 17 service days: the sentence says so instead of claiming 28.
    expect(
      screen.getByText("Over the 17 days tracked so far, 5% of line 720's trips never ran."),
    ).toBeTruthy();
    expect(screen.getByText("Range: 4 to 6%.")).toBeTruthy();
    expect(
      screen.getByText(
        "58 of 1,228 trips with a known outcome. 30 were announced cancellations and 28 were unplanned missed trips.",
      ),
    ).toBeTruthy();
  });

  it("says the past 28 days once the archive covers them", () => {
    render(<LineSummary name="720" rates={{ ...RATES, n_service_days: 28 }} />);
    expect(
      screen.getByText("Over the past 28 days, 5% of line 720's trips never ran."),
    ).toBeTruthy();
  });

  it("says not enough data instead of a number when suppressed", () => {
    const { container } = render(<LineSummary name="720" rates={SUPPRESSED} />);
    expect(container.textContent).toBe("Not enough data yet to say how reliable line 720 is.");
    expect(container.textContent).not.toMatch(/\d+%/);
  });
});
