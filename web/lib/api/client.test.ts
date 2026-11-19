import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiGet, buildPath, buildQuery } from "./client";

describe("buildPath and buildQuery", () => {
  it("encodes path parameters", () => {
    expect(buildPath("/v1/lines/{line}/stops", { line: "10 48/x" })).toBe(
      "/v1/lines/10%2048%2Fx/stops",
    );
  });

  it("refuses a missing path parameter", () => {
    expect(() => buildPath("/v1/lines/{line}", {})).toThrow("missing path parameter line");
  });

  it("refuses segments that would change the route", () => {
    for (const line of ["", ".", ".."]) {
      expect(() => buildPath("/v1/lines/{line}/stops", { line })).toThrow("bad path parameter");
    }
  });

  it("drops unset query values", () => {
    expect(buildQuery({ direction_id: 0, window: undefined, day_type: null })).toBe(
      "?direction_id=0",
    );
    expect(buildQuery(undefined)).toBe("");
  });
});

describe("apiGet", () => {
  beforeEach(() => vi.stubEnv("GHOSTBUS_API_URL", "https://api.example.test/"));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("fetches the typed path with a 5-minute revalidate", async () => {
    const fetchMock = vi.fn(async () => Response.json({ lines: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const body = await apiGet("/v1/lines/{line}/reliability", {
      params: { line: "720" },
      query: { direction_id: 0, window: "28d" },
    });
    expect(body).toEqual({ lines: [] });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/v1/lines/720/reliability?direction_id=0&window=28d",
      { next: { revalidate: 300 } },
    );
  });

  it("turns a problem document into an ApiError with its status", async () => {
    vi.stubGlobal("fetch", async () =>
      Response.json({ title: "Line not found", status: 404 }, { status: 404 }),
    );
    const error = await apiGet("/v1/lines/{line}", { params: { line: "nope" } }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, message: "404 Line not found" });
  });

  it("requires path parameters at compile time (checked by tsc, not run)", () => {
    const typeChecks = () => {
      // @ts-expect-error: `/v1/lines/{line}` needs params.line
      void apiGet("/v1/lines/{line}");
      // @ts-expect-error: unknown query parameter
      void apiGet("/v1/lines", { query: { colour: "red" } });
      // @ts-expect-error: the reliability grid requires query.direction_id
      void apiGet("/v1/lines/{line}/reliability", { params: { line: "720" } });
      // Optional query parameters may be left out.
      void apiGet("/v1/lines");
      void apiGet("/v1/lines/{line}", { params: { line: "720" } });
    };
    expect(typeChecks).toBeTypeOf("function");
  });

  it("keeps the status when the error body isn't a problem document", async () => {
    for (const body of ["null", '"oops"', "<html>"]) {
      vi.stubGlobal(
        "fetch",
        async () => new Response(body, { status: 502, statusText: "Bad Gateway" }),
      );
      await expect(apiGet("/v1/lines")).rejects.toMatchObject({
        status: 502,
        message: "502 Bad Gateway",
      });
    }
  });

  it("fails loudly when the API URL isn't configured", async () => {
    vi.stubEnv("GHOSTBUS_API_URL", "");
    await expect(apiGet("/v1/lines")).rejects.toThrow("GHOSTBUS_API_URL is not set");
  });
});
