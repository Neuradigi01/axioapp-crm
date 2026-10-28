// One-off verification of the shared `initials` helper from
// src/app/core/services/text.util.ts. Walks representative name
// shapes through the function and reports pass/fail.

function initials(name) {
  if (!name) return '?';
  const result = name
    .split(/\s+/)
    .filter((p) => p.length > 0)
    .slice(0, 2)
    .map((p) => p[0].toUpperCase())
    .join('');
  return result.length > 0 ? result : '?';
}

const cases = [
  ['typical two-word name',    'John Doe',         'JD'],
  ['lowercase',                'alice smith',      'AS'],
  ['extra inner whitespace',   'John   Doe',       'JD'],
  ['leading/trailing spaces',  '  Alice  Smith  ', 'AS'],
  ['single word',              'Madonna',          'M'],
  ['three+ words, capped at 2','Mary Anne Smith',  'MA'],
  ['null',                     null,               '?'],
  ['undefined',                undefined,          '?'],
  ['empty string',             '',                 '?'],
  ['only whitespace',          '   ',              '?'],
  ['single char',              'A',                'A'],
  ['unicode name',             'José García',      'JG'],
  ['mixed case kept upper',    'jOhN dOe',         'JD'],
  ['tab separated',            'John\tDoe',        'JD'],
];

let pass = 0, fail = 0;
for (const [label, input, expected] of cases) {
  const actual = initials(input);
  const ok = actual === expected;
  if (ok) pass++; else fail++;
  const repr = (x) => x === undefined ? 'undefined' : JSON.stringify(x);
  console.log(
    `${ok ? 'PASS' : 'FAIL'}  ${label.padEnd(28)}` +
    `  input=${repr(input).padEnd(22)} expected=${repr(expected).padEnd(6)} got=${repr(actual)}`
  );
}
console.log(`\n--- ${pass}/${cases.length} passed, ${fail} failed ---`);
process.exit(fail === 0 ? 0 : 1);
