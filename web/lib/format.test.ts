import { describe, expect, it } from "vitest";

import { NOT_ENOUGH_DATA, count, percent, percentRange } from "./format";

describe("percent", () => {
  it("rounds to whole percent", () => {
    expect(percent(0.0472)).toBe("5%");
    expect(percent(0.95)).toBe("95%");
    expect(percent(0)).toBe("0%");
    expect(percent(1)).toBe("100%");
  });

  it("never shows a small nonzero rate as 0%", () => {
    expect(percent(0.004)).toBe("0.4%");
    expect(percent(0.0001)).toBe("<0.1%");
    expect(percent(0.0009)).toBe("<0.1%");
  });

  it("never shows a rate just under 100% as 100%", () => {
    expect(percent(0.996)).toBe("99.6%");
    expect(percent(0.99999)).toBe(">99.9%");
  });

  it("shows a suppressed rate as not enough data, never zero", () => {
    expect(percent(null)).toBe(NOT_ENOUGH_DATA);
    expect(percent(undefined)).toBe(NOT_ENOUGH_DATA);
    expect(percent(Number.NaN)).toBe(NOT_ENOUGH_DATA);
  });
});

describe("percentRange", () => {
  it("reads as a range", () => {
    expect(percentRange(0.038, 0.066)).toBe("4 to 7%");
  });

  it("keeps both ends apart and honest at the edges", () => {
    expect(percentRange(0.046, 0.054)).toBe("4.6 to 5.4%");
    expect(percentRange(0.0004, 0.02)).toBe("under 0.1 to 2.0%");
    expect(percentRange(0.97, 0.99999)).toBe("97.0 to over 99.9%");
    expect(percentRange(0, 0.05)).toBe("0 to 5%");
  });

  it("is absent when either end is missing", () => {
    expect(percentRange(null, 0.066)).toBeNull();
    expect(percentRange(0.038, undefined)).toBeNull();
  });
});

describe("count", () => {
  it("groups thousands and marks missing counts", () => {
    expect(count(12400)).toBe("12,400");
    expect(count(null)).toBe("–");
  });
});
