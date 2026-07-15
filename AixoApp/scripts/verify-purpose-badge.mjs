// Verify purposeBadgeClass produces the same Tailwind classes the
// 4 deleted copies produced. Output strings are checked exactly.

function purposeBadgeClass(purpose) {
  switch (purpose) {
    case 'measurement':  return 'bg-sky-100 text-sky-700 ring-sky-200';
    case 'installation': return 'bg-amber-100 text-amber-700 ring-amber-200';
    case 'inspection':   return 'bg-violet-100 text-violet-700 ring-violet-200';
    default:             return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
  }
}

const cases = [
  ['measurement',  'bg-sky-100 text-sky-700 ring-sky-200'],
  ['installation', 'bg-amber-100 text-amber-700 ring-amber-200'],
  ['inspection',   'bg-violet-100 text-violet-700 ring-violet-200'],
  ['delivery',     'bg-zinc-100 text-zinc-700 ring-zinc-200'],     // falls to default
  ['repair',       'bg-zinc-100 text-zinc-700 ring-zinc-200'],     // unknown
  ['',             'bg-zinc-100 text-zinc-700 ring-zinc-200'],     // empty
];

let pass = 0, fail = 0;
for (const [input, expected] of cases) {
  const got = purposeBadgeClass(input);
  const ok = got === expected;
  if (ok) pass++; else fail++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  purpose=${JSON.stringify(input).padEnd(15)} → ${got}`);
}
console.log(`\n--- ${pass}/${cases.length} passed, ${fail} failed ---`);
process.exit(fail === 0 ? 0 : 1);
