import { describe, expect, it } from "vitest";

import { RATES, SUPPRESSED } from "@/tests/fixtures";
import { byReliability, matching } from "./lines";

const line = (slug: string, rate: number | null) => ({
  line: slug.replace("-", "/"),
  line_slug: slug,
  display_name: slug.replace("-", "/"),
  line_kind: null,
  summary: rate === null ? SUPPRESSED : { ...RATES, missed_rate: rate },
});

const LINES = [line("2", 0.03), line("10-48", null), line("720", 0.08), line("728", 0.01)];

describe("matching", () => {
  it("finds lines by number prefix", () => {
    expect(matching(LINES, "72").map((l) => l.line_slug)).toEqual(["720", "728"]);
    expect(matching(LINES, " 10/4").map((l) => l.line_slug)).toEqual(["10-48"]);
    expect(matching(LINES, "")).toHaveLength(4);
    expect(matching(LINES, "999")).toEqual([]);
    expect(matching(LINES, "  Line 720 ").map((l) => l.line_slug)).toEqual(["720"]);
    expect(matching(LINES, "   ")).toHaveLength(4);
  });
});

describe("byReliability", () => {
  it("puts the least reliable first and lines without enough data last, never as zero", () => {
    expect(byReliability(LINES).map((l) => l.line_slug)).toEqual(["720", "2", "728", "10-48"]);
  });

  it("treats a suppressed summary as no data even if a rate is present", () => {
    const sneaky = { ...line("5", 0.5), summary: { ...RATES, missed_rate: 0.5, suppressed: true } };
    expect(byReliability([sneaky, line("2", 0.03)]).map((l) => l.line_slug)).toEqual(["2", "5"]);
  });
});
