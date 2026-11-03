import { defineConfig } from "../site/node_modules/vitest/dist/config.js";

export default defineConfig({
  root: ".",
  cacheDir: "site/node_modules/.vite",
  esbuild: { jsx: "automatic" },
  test: {
    environment: "node",
    include: ["evals/analysis-2026-11-03.test.tsx"],
    globals: true,
  },
});
