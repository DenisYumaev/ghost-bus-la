/** Answers a mocked apiGet from a table keyed by path (plus `#direction` for grids). */
import type { Mock } from "vitest";

export function answer(apiGet: Mock, routes: Record<string, unknown>) {
  apiGet.mockImplementation(
    async (path: string, options?: { query?: { direction_id?: number } }) => {
      const id = options?.query?.direction_id;
      const value = routes[id !== undefined ? `${path}#${id}` : path];
      if (value instanceof Error) throw value;
      if (value === undefined) throw new Error(`unexpected ${path}`);
      return value;
    },
  );
}
