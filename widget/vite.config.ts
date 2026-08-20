import { defineConfig, type Plugin } from "vite";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Library build — one IIFE bundle at `dist/v1/widget.js`.
 *
 * IIFE (immediately-invoked function expression) is the correct format
 * for a drop-in `<script src=".../widget.js">` snippet: it self-executes,
 * leaks nothing to the global scope, and works in a plain classic
 * `<script>` tag without requiring the customer to add `type="module"`.
 * (An ESM build fails with `Uncaught SyntaxError: Unexpected token
 * 'export'` when loaded as a classic script.)
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
 *
 * In dev mode the `serveBuiltWidget` plugin maps `/v1/widget.js` to
 * the most-recent `dist/v1/widget.js` so the dev test page (which
 * mirrors the customer install snippet exactly) keeps working without
 * a separate static server. Run `npm run build` first to populate
 * `dist/`, then `npm run dev` for live editing of the test page.
 */
function serveBuiltWidget(): Plugin {
  const builtPath = path.join(__dirname, "dist", "v1", "widget.js");
  const builtMapPath = `${builtPath}.map`;
  return {
    name: "serve-built-widget",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url) return next();
        const url = req.url.split("?")[0];
        if (url === "/v1/widget.js" || url === "/v1/widget.js.map") {
          const file =
            url === "/v1/widget.js.map" ? builtMapPath : builtPath;
          if (!fs.existsSync(file)) {
            res.statusCode = 404;
            res.setHeader("Content-Type", "text/plain");
            res.end(
              "widget bundle not built — run `npm run build` once, " +
                "then this URL will serve dist/v1/widget.js"
            );
            return;
          }
          res.setHeader(
            "Content-Type",
            url.endsWith(".map")
              ? "application/json"
              : "application/javascript"
          );
          res.setHeader("Access-Control-Allow-Origin", "*");
          res.setHeader("Cache-Control", "no-store");
          fs.createReadStream(file).pipe(res);
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [serveBuiltWidget()],
  build: {
    lib: {
      // Loader is the bundle's entry — it auto-discovers the
      // <script> tag on customer pages and calls `init()`.
      entry: "src/loader.ts",
      // IIFE so the bundle drops into any `<script>` tag on a
      // customer's site without requiring `type="module"`. The
      // `name` gates what the wrapper exposes on `window`; we
      // keep it namespaced but no one is expected to reach for it.
      formats: ["iife"],
      name: "CrmAiAssistantWidget",
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
