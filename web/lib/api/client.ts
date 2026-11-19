/**
 * Typed GET for the public API. Response types come from the generated `schema.ts` (never
 * hand-written; web spec section 2), so a field the API drops is a type error here.
 */
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

type Get<P extends keyof paths> = paths[P]["get"];
export type Ok<P extends keyof paths> =
  Get<P> extends { responses: { 200: { content: { "application/json": infer B } } } } ? B : never;
type Params<P extends keyof paths> =
  Get<P> extends { parameters: { path: infer T } }
    ? T extends Record<string, unknown>
      ? T
      : never
    : never;
type Query<P extends keyof paths> = Get<P> extends { parameters: { query?: infer Q } } ? Q : never;

/** A non-2xx answer: the problem document's status and title (API spec section 2). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    title: string,
  ) {
    super(`${status} ${title}`);
    this.name = "ApiError";
  }
}

export function apiBase(): string {
  const base = process.env.GHOSTBUS_API_URL;
  if (!base) throw new Error("GHOSTBUS_API_URL is not set");
  return base.replace(/\/+$/, "");
}

/** `/v1/lines/{line}` with `{line: "10-48"}` → `/v1/lines/10-48`, each value URL-encoded. */
export function buildPath(template: string, params: Record<string, unknown> = {}): string {
  return template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = params[name];
    if (value === undefined) throw new Error(`missing path parameter ${name}`);
    const text = String(value);
    // An empty, "." or ".." segment would change which route is fetched (dot segments are
    // resolved even when percent-encoded).
    if (text === "" || text === "." || text === "..") throw new Error(`bad path parameter ${name}`);
    return encodeURIComponent(text);
  });
}

export function buildQuery(query: Record<string, unknown> | undefined): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

type HasRequiredKeys<T> = [T] extends [never]
  ? false
  : Record<string, never> extends T
    ? false
    : true;

/** `params` when the path has parameters; `query` required when a query parameter is. */
type Options<P extends keyof paths> = { revalidate?: number } & ([Params<P>] extends [never]
  ? { params?: never }
  : { params: Params<P> }) &
  (HasRequiredKeys<NonNullable<Query<P>>> extends true
    ? { query: NonNullable<Query<P>> }
    : { query?: Query<P> });

type Args<P extends keyof paths> = [Params<P>] extends [never]
  ? HasRequiredKeys<NonNullable<Query<P>>> extends true
    ? [Options<P>]
    : [Options<P>?]
  : [Options<P>];

/** GET a path. Missing path parameters or required query parameters are compile errors. */
/** For a page's secondary sections: null for a 404 or 503 answer, so the section can say it's
 * unavailable while the rest of the page renders. Anything else (a network failure) throws. */
export async function orNull<T>(request: Promise<T>): Promise<T | null> {
  try {
    return await request;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 503)) return null;
    throw error;
  }
}

export async function apiGet<P extends keyof paths>(
  path: P,
  ...[options = {} as Options<P>]: Args<P>
): Promise<Ok<P>> {
  const url = apiBase() + buildPath(path, options.params) + buildQuery(options.query ?? undefined);
  // Server components cache for 5 minutes, matching the API's max-age (web spec section 2).
  const response = await fetch(url, { next: { revalidate: options.revalidate ?? 300 } });
  if (!response.ok) {
    const problem: unknown = await response.json().catch(() => null);
    const title =
      problem !== null &&
      typeof problem === "object" &&
      "title" in problem &&
      typeof problem.title === "string"
        ? problem.title
        : response.statusText;
    throw new ApiError(response.status, title);
  }
  return (await response.json()) as Ok<P>;
}
