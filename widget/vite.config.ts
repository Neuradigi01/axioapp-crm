import { defineConfig } from "vite";

/**
 * Library build — one ES module at `dist/v1/widget.js`.
 *
 * The `/v1/` segment in the output path is intentional: the customer-
 * facing install snippet pins the major version (`/v1/widget.js`) so
 * a future v2 with breaking changes ships at `/v2/widget.js` without
 * disturbing existing customer installs.
 *
 * `cors: true` on both `server` (vite dev) and `preview` (built bundle
 * served back) so a test HTML page on any origin can fetch the
 * bundle locally for verification.
 *
 * `dev/` is exposed as part of Vite's static-serve root via the
 * default `publicDir` behaviour — `dev/test-host.html` resolves at
 * `http://localhost:5173/dev/test-host.html`.
 */
export default defineConfig({
  build: {
    lib: {
      // Loader is the bundle's entry — it auto-discovers the
      // <script> tag on customer pages and calls `init()`. The
      // loader re-exports `init` + types so manual integrations
      // can still `import { init } from "/v1/widget.js"`.
      entry: "src/loader.ts",
      formats: ["es"],
      fileName: () => "v1/widget.js",
    },
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
    minify: "esbuild",
    rollupOptions: {
      output: {
        entryFileNames: "v1/widget.js",
      },
    },
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
    cors: true,
  },
  preview: {
    port: 5173,
    host: "0.0.0.0",
    cors: true,
  },
  test: {
    environment: "jsdom",
  },
});
