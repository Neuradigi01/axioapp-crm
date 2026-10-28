/**
 * Formats an amount as an Indian-rupee display string with locale-correct
 * lakhs / crores grouping. Decimals are dropped. Falls back to an
 * em-dash when the input can't be coerced to a finite number, so
 * callers don't have to guard before calling.
 *
 *   fmtInr(15000)       → '₹15,000'
 *   fmtInr(175000)      → '₹1,75,000'    (Indian grouping)
 *   fmtInr('25000.50')  → '₹25,001'      (rounded by toLocaleString)
 *   fmtInr(null)        → '₹0'
 *   fmtInr('not-a-num') → '—'
 *
 * NB: this is NOT a substitute for the compact-form formatter used by
 * the custom-orders list page (e.g. '₹1.8L', '₹15.0K'). That lives
 * inline at custom-orders.page.ts as an intentionally different
 * display format for space-constrained cards.
 */
export function fmtInr(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '—';
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}
