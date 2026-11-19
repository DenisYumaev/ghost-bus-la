import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StaleNotice } from "./StaleNotice";

describe("StaleNotice", () => {
  const asOf = "2026-12-01T17:40:12Z";

  it("renders nothing while data is fresh", () => {
    const { container } = render(
      <StaleNotice dataAsOf={asOf} now={new Date("2026-12-01T18:30:00Z")} />,
    );
    expect(container.textContent).toBe("");
  });

  it("says when the data is from once it is over an hour old", () => {
    const { container } = render(
      <StaleNotice dataAsOf={asOf} now={new Date("2026-12-01T19:00:00Z")} />,
    );
    expect(container.textContent).toBe(
      "This data may be out of date: it was last updated Tue, Dec 1 at 9:40 AM.",
    );
  });
});
