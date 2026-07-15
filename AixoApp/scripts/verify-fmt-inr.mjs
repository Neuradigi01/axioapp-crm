// Verify the shared fmtInr against representative amounts.
function fmtInr(value) {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '—';
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

const cases = [
  // [label, input, expected]
  ['typical price',            15000,         '₹15,000'],
  ['Indian lakhs grouping',    175000,        '₹1,75,000'],
  ['crores grouping',          12500000,      '₹1,25,00,000'],
  ['zero',                     0,             '₹0'],
  ['numeric string',           '25000',       '₹25,000'],
  ['string with decimals',     '25000.50',    '₹25,001'],  // rounded by toLocaleString
  ['null',                     null,          '₹0'],
  ['undefined',                undefined,     '₹0'],
  ['non-numeric string',       'not-a-num',   '—'],
  ['NaN',                      NaN,           '—'],
  ['negative price',           -500,          '₹-500'],
];

let pass = 0, fail = 0;
for (const [label, input, expected] of cases) {
  const got = fmtInr(input);
  const ok = got === expected;
  if (ok) pass++; else fail++;
  const repr = (x) => x === undefined ? 'undefined' : JSON.stringify(x);
  console.log(
    `${ok ? 'PASS' : 'FAIL'}  ${label.padEnd(28)}  input=${repr(input).padEnd(14)} expected=${expected.padEnd(15)} got=${got}`
  );
}
console.log(`\n--- ${pass}/${cases.length} passed, ${fail} failed ---`);
process.exit(fail === 0 ? 0 : 1);
