// Verify deriveApiOrigin against representative environment.apiBaseUrl
// shapes. The function lives in src/app/core/services/url.util.ts.
// We re-create it here because Node can't import the .ts module
// directly without a build step.

function deriveApiOrigin(apiBaseUrl, fallbackOrigin = 'http://localhost:4200') {
  try {
    return new URL(apiBaseUrl, fallbackOrigin).origin;
  } catch {
    return '';
  }
}

const cases = [
  ['dev: localhost API on :8000',  'http://localhost:8000/api/v1', 'http://localhost:8000'],
  ['prod: https host',             'https://api.example.com/v1',   'https://api.example.com'],
  ['custom port',                  'https://api.example.com:9443/v1', 'https://api.example.com:9443'],
  ['same-origin relative API',     '/api/v1',                       'http://localhost:4200'],
  ['empty string',                 '',                              'http://localhost:4200'],
  ['malformed URL',                'not a url at all',              'http://localhost:4200'],
];

let pass = 0, fail = 0;
for (const [label, input, expected] of cases) {
  const got = deriveApiOrigin(input);
  const ok = got === expected;
  if (ok) pass++; else fail++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label.padEnd(32)}  input=${JSON.stringify(input).padEnd(36)} → ${JSON.stringify(got)}`);
}
console.log(`\n--- ${pass}/${cases.length} passed, ${fail} failed ---`);
process.exit(fail === 0 ? 0 : 1);
