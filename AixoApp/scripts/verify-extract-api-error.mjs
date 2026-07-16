// One-off verification: walk a captured HTTP error body through the
// same logic that lives in `extractApiError(err)` and report which
// branch fires + what the function would return.
//
// This is a verification harness for the extractError → extractApiError
// consolidation. It is NOT part of the app build.

function extractApiError(body) {
  // Mirrors src/app/core/services/api-error.util.ts exactly. The
  // Angular function takes an HttpErrorResponse; here we pass the
  // pre-parsed `.error` body directly so the script can run under Node.
  if (typeof body === 'string') return { branch: 1, value: body };
  if (body && typeof body === 'object') {
    const candidate =
      body.message ?? body.detail;
    if (typeof candidate === 'string') return { branch: 2, value: candidate };
  }
  return { branch: 4, value: null };
}

const cases = JSON.parse(process.argv[2]);
let pass = 0, fail = 0;
for (const c of cases) {
  let parsed;
  try { parsed = JSON.parse(c.body); } catch { parsed = c.body; }
  const r = extractApiError(parsed);
  const ok = r.value !== null;
  if (ok) pass++; else fail++;
  console.log(
    `[HTTP ${c.code}] ${c.label}\n` +
    `  body:   ${c.body}\n` +
    `  branch: ${r.branch}\n` +
    `  result: ${JSON.stringify(r.value)}  ${ok ? 'OK' : 'NULL (caller falls back to default copy)'}\n`
  );
}
console.log(`---\n${pass} extracted a message, ${fail} returned null.`);
