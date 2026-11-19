import { describe, expect, it } from "vitest";

import en from "@/messages/en.json";
import { t } from "./messages";

describe("messages", () => {
  it("looks up a string", () => {
    expect(t("site.name")).toBe("Ghost Bus LA");
  });

  it("states the disclaimer the product copy requires (hard rule 12)", () => {
    expect(t("site.disclaimer")).toContain("not affiliated with LA Metro");
  });

  it("never says Metro hides data (hard rule 12)", () => {
    for (const text of Object.values(en))
      expect(text.toLowerCase()).not.toMatch(/hid(e|es|ing|den)/);
  });
});
