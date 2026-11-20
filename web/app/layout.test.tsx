import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import RootLayout, { metadata } from "./layout";

// The name sounds official, so independence must show on every page and in search results
// (hard rule 12).
describe("root layout", () => {
  it("shows the disclaimer in the footer of every page", () => {
    const { container } = render(<RootLayout>{null}</RootLayout>, { container: document });
    expect(container.querySelector("footer")?.textContent).toBe(
      "LA Bus Reliability is not affiliated with LA Metro.",
    );
  });

  it("says so in the search description too", () => {
    expect(metadata.description).toContain("not affiliated with LA Metro");
  });
});
