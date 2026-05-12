import { Pipe, PipeTransform } from '@angular/core';

/**
 * Formats a number / numeric string into Indian-rupee currency using
 * the en-IN locale grouping (lakhs / crores). `null` / `undefined` /
 * empty values render as an em-dash so caller templates don't have
 * to guard.
 *
 *   1500          → ₹1,500.00
 *   175000        → ₹1,75,000.00
 *   "175000.00"   → ₹1,75,000.00
 *   null          → —
 *
 * The `compact` option strips trailing `.00` for tidy card display:
 *
 *   formatINR(150000, true) → ₹1,50,000
 */
@Pipe({ name: 'formatINR', standalone: true })
export class InrPipe implements PipeTransform {
  transform(
    value: number | string | null | undefined,
    compact = false,
  ): string {
    if (value === null || value === undefined || value === '') return '—';
    const n = typeof value === 'string' ? Number(value) : value;
    if (!Number.isFinite(n)) return '—';
    const formatter = new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      minimumFractionDigits: compact && Number.isInteger(n) ? 0 : 2,
      maximumFractionDigits: compact && Number.isInteger(n) ? 0 : 2,
    });
    return formatter.format(n);
  }
}
