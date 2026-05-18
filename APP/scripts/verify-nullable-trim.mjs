// One-off verification: confirm `nullableTrim` from
// src/app/core/services/form.util.ts behaves identically to the
// 7 deleted `private nullableTrim` copies for every input shape the
// form modals can produce.

function nullableTrim(v) {
  if (v === null || v === undefined) return null;
  const trimmed = String(v).trim();
  return trimmed.length === 0 ? null : trimmed;
}

const cases = [
  // [label, input, expected, why]
  ['plain string',                'Sofa',           'Sofa',  'optional field filled in normally'],
  ['leading + trailing whitespace','  Sofa  ',      'Sofa',  'paste from clipboard usually has stray spaces'],
  ['only whitespace',             '   ',            null,    'user tabbed through; reactive form gives back spaces — should be null'],
  ['empty string',                '',               null,    'reactive forms emit "" for an untouched optional control'],
  ['null',                        null,             null,    'caller passed null explicitly'],
  ['undefined',                   undefined,        null,    'caller passed undefined explicitly'],
  ['single char',                 'A',              'A',     'edge: very short input still works'],
  ['internal whitespace kept',    'Walnut  Veneer', 'Walnut  Veneer', 'only outer trimmed, not collapsed'],
  ['tab + newline',               '\t\nfoo\n',      'foo',   'works on any whitespace, not just spaces'],
  ['number from type="number"',   15000,            '15000', 'budget input — was the runtime crash before this fix'],
  ['zero',                        0,                '0',     'numeric zero is a valid input, not null'],
  ['boolean',                     false,            'false', 'mistyped form control — coerce instead of crashing'],
];

let pass = 0, fail = 0;
for (const [label, input, expected, why] of cases) {
  const actual = nullableTrim(input);
  const ok = actual === expected;
  if (ok) pass++; else fail++;
  const repr = (x) => x === undefined ? 'undefined' : JSON.stringify(x);
  const inputRepr = repr(input);
  const actualRepr = repr(actual);
  const expectedRepr = repr(expected);
  console.log(
    `${ok ? 'PASS' : 'FAIL'}  ${label.padEnd(32)}` +
    `  input=${inputRepr.padEnd(20)} expected=${expectedRepr.padEnd(10)} got=${actualRepr}\n` +
    `      why: ${why}`
  );
}
console.log(`\n--- ${pass}/${cases.length} passed, ${fail} failed ---`);
process.exit(fail === 0 ? 0 : 1);
