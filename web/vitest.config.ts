import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: {
    environment: "jsdom",
    // Web spec section 10: times render in Los Angeles whatever the viewer's zone. Running the
    // tests in a different zone proves the code never relies on the machine's.
    env: { TZ: "Asia/Tokyo" },
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", ".next/**"],
  },
});
