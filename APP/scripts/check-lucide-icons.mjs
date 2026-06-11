#!/usr/bin/env node
/**
 * Pre-build audit: every <lucide-icon name="X"> in the Angular templates
 * must have a matching entry in app.config.ts's LucideAngularModule.pick({...}).
 *
 * Lucide-angular's icon registry is opt-in — only icons listed in the
 * pick block render. A missing icon throws mid-render and silently
 * blanks the rest of the surrounding template (downstream click handlers
 * never get wired, inputs disappear, etc). The bug is invisible to
 * TypeScript because the icon name is a string in HTML.
 *
 * Run on its own:
 *   node scripts/check-lucide-icons.mjs
 *
 * Wired into `prebuild` in package.json so `npm run build` aborts when
 * a template references an unregistered icon.
 *
 * Exit codes:
 *   0 — all icons registered
 *   1 — at least one icon missing (lists them)
 *   2 — couldn't parse the pick block (app.config.ts shape changed)
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const appRoot = join(__dirname, '..');
const srcRoot = join(appRoot, 'src', 'app');

/** Recursive directory walk — kept inline so this script has zero
 *  dependencies. Skips node_modules and *.spec.ts files. */
function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules') continue;
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      yield* walk(full);
    } else if (
      (full.endsWith('.html') || full.endsWith('.ts')) &&
      !full.endsWith('.spec.ts')
    ) {
      yield full;
    }
  }
}

// --- Convert lucide-angular PascalCase identifiers to kebab-case ----
// Rules mirror lucide-angular's internal name table:
//   lowercase|digit -> Uppercase  : insert dash
//   letter -> digit                : insert dash
//   UPPER -> UpperLower (acronym boundary): insert dash
function toKebab(s) {
  return s
    .replace(/([a-z])([A-Z])/g, '$1-$2')
    .replace(/([A-Za-z])([0-9])/g, '$1-$2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1-$2')
    .toLowerCase();
}

// --- Walk templates for <lucide-icon name="X"> --------------------
// We also catch the same construct inside inline templates in .ts
// component files (the billing cards use inline templates).
const USAGE_RE = /<lucide-icon[^>]*\sname=["']([a-zA-Z][a-zA-Z0-9-]*)["']/g;
const used = new Map(); // name -> [{file, line}]
for (const file of walk(srcRoot)) {
  const txt = readFileSync(file, 'utf8');
  // Skip the very file we're describing — and skip our own script.
  if (file.endsWith('check-lucide-icons.mjs')) continue;
  const lines = txt.split('\n');
  for (let i = 0; i < lines.length; i++) {
    USAGE_RE.lastIndex = 0;
    let m;
    while ((m = USAGE_RE.exec(lines[i])) !== null) {
      const name = m[1];
      if (!used.has(name)) used.set(name, []);
      used.get(name).push({ file: relative(appRoot, file), line: i + 1 });
    }
  }
}

// --- Read the registered pick({...}) block --------------------------
const cfg = readFileSync(join(srcRoot, 'app.config.ts'), 'utf8');
const pickMatch = cfg.match(/LucideAngularModule\.pick\(\{([^}]+)\}\)/s);
if (!pickMatch) {
  console.error(
    '[check-lucide-icons] Could not find LucideAngularModule.pick({...}) in app.config.ts.',
  );
  console.error('  The script needs that block to know what is registered.');
  console.error('  If you moved registration, update this script.');
  process.exit(2);
}
const registered = new Set(
  Array.from(pickMatch[1].matchAll(/\b([A-Z][A-Za-z0-9]*)\b/g)).map((m) =>
    toKebab(m[1]),
  ),
);

// --- Diff & report --------------------------------------------------
const missing = [...used.keys()].filter((n) => !registered.has(n)).sort();

if (missing.length === 0) {
  console.log(
    `[check-lucide-icons] OK — ${used.size} distinct icons used, all registered.`,
  );
  process.exit(0);
}

console.error(
  `[check-lucide-icons] ${missing.length} icon${missing.length === 1 ? '' : 's'} used in templates but NOT registered in app.config.ts:\n`,
);
for (const name of missing) {
  // Convert kebab back to PascalCase for the register hint.
  const pascal = name
    .split('-')
    .map((p) => p[0].toUpperCase() + p.slice(1))
    .join('');
  console.error(`  ✗ "${name}"  →  add \`${pascal}\` to app.config.ts`);
  for (const loc of used.get(name).slice(0, 3)) {
    console.error(`      used in ${loc.file}:${loc.line}`);
  }
  const extra = used.get(name).length - 3;
  if (extra > 0) console.error(`      …and ${extra} more`);
}
console.error(
  '\nFix: add the icons above to BOTH the import list and the LucideAngularModule.pick({...}) block in src/app/app.config.ts.',
);
process.exit(1);
