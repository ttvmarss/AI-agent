import { defineConfig } from "vite";

// The UI is built straight into the Python package, so `pip install` (or a git checkout) ships a ready-to-run interface and nobody needs Node
// to *use* PRAXIS. Node is only for working on the UI itself.
export default defineConfig({
  base: "./",
  build: {
    outDir: "../praxis/ui/static",
    emptyOutDir: true,
    target: "es2022",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8765" } },
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
});
