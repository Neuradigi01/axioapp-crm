/**
 * Bundle-size guard. Runs at the end of `npm run build` and fails
 * loudly if the gzipped widget bundle exceeds the 30 KB ceiling.
 *
 * Why a hard ceiling: the widget is served from the customer-website
 * critical path on (often) slow Indian 3G connections. Over 30 KB
 * gzipped and the form takes > 1s to render on a real-world device,
 * which is enough delay that conversion measurably drops.
 *
 * Run: `tsx scripts/check-size.ts`
 */
import { gzipSync } from "node:zlib";
import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const MAX_GZIPPED_BYTES = 30 * 1024;

const bundlePath = resolve("dist/v1/widget.js");

let raw: Buffer;
try {
  raw = readFileSync(bundlePath);
} catch {
  console.error(
    `[check-size] FAIL: bundle not found at ${bundlePath}. ` +
      "Did `vite build` run first?",
  );
  process.exit(1);
}

const rawBytes = statSync(bundlePath).size;
const gzipped = gzipSync(raw);
const gzippedBytes = gzipped.length;

const fmt = (n: number) => `${(n / 1024).toFixed(2)} KB`;

console.log(
  `[check-size] widget.js: ${fmt(rawBytes)} raw / ${fmt(gzippedBytes)} gzipped ` +
    `(ceiling ${fmt(MAX_GZIPPED_BYTES)})`,
);

if (gzippedBytes > MAX_GZIPPED_BYTES) {
  console.error(
    `[check-size] FAIL: gzipped size ${fmt(gzippedBytes)} exceeds ` +
      `the ${fmt(MAX_GZIPPED_BYTES)} ceiling.`,
  );
  process.exit(1);
}

console.log("[check-size] OK");
