import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // Web spec section 2: strict TypeScript, no `any`.
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
  globalIgnores([".next/**", "node_modules/**", "next-env.d.ts", "lib/api/schema.ts"]),
]);
