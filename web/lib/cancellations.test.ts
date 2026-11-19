import { describe, expect, it } from "vitest";

import { cancelledText } from "./cancellations";

describe("cancelledText", () => {
  it("counts in plain words with the time, never 'right now'", () => {
    expect(cancelledText(0, "9:38 AM")).toBe(
      "As of 9:38 AM, Metro's realtime feed listed no trips as canceled.",
    );
    expect(cancelledText(1, "9:38 AM")).toBe(
      "As of 9:38 AM, Metro's realtime feed listed 1 trip as canceled.",
    );
    expect(cancelledText(1204, "9:38 AM")).toBe(
      "As of 9:38 AM, Metro's realtime feed listed 1,204 trips as canceled.",
    );
  });
});
