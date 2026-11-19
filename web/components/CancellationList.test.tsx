import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CANCELLATIONS } from "@/tests/fixtures";
import { CancellationList, noticeText } from "./CancellationList";

describe("noticeText", () => {
  it("reads advance notice in minutes or hours", () => {
    expect(noticeText(900)).toBe("announced 15 min before departure");
    expect(noticeText(4200)).toBe("announced 1 h 10 min before departure");
  });

  it("never shows a negative number (ADR-029)", () => {
    expect(noticeText(-300)).toBe("announced after departure");
    expect(noticeText(null)).toBeNull();
  });
});

describe("CancellationList", () => {
  it("lists each trip with local time, headsign and notice", () => {
    render(<CancellationList data={CANCELLATIONS} />);
    expect(screen.getByText("10:30 AM toward Santa Monica")).toBeTruthy();
    expect(screen.getByText("announced 1 h 10 min before departure")).toBeTruthy();
    expect(screen.getByText("As of 9:38 AM.")).toBeTruthy();
  });

  it("leaves out a missing headsign rather than printing an empty one", () => {
    const [trip] = CANCELLATIONS.cancellations;
    render(
      <CancellationList
        data={{ ...CANCELLATIONS, cancellations: [{ ...trip!, headsign: null }] }}
      />,
    );
    expect(screen.getByText("10:30 AM")).toBeTruthy();
    expect(screen.queryByText(/toward/)).toBeNull();
  });

  it("says so when nothing is canceled", () => {
    render(<CancellationList data={{ ...CANCELLATIONS, cancellations: [] }} />);
    expect(screen.getByText("No announced cancellations for this line right now.")).toBeTruthy();
  });

  it("warns when the list is stale instead of presenting it as current", () => {
    render(<CancellationList data={{ ...CANCELLATIONS, stale: true }} />);
    expect(screen.getByRole("status").textContent).toBe(
      "This list may be out of date: our latest data is from 9:38 AM.",
    );
    expect(screen.queryByText(/^As of/)).toBeNull();
  });
});
