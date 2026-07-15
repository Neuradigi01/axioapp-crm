import { Pipe, PipeTransform } from '@angular/core';

/**
 * Formats an absolute timestamp as a relative-time string suitable for
 * dense list rows ("2h ago", "3d ago", "24 Apr"). Buckets:
 *
 *   < 60s      → "just now"
 *   < 60m      → "<N>m ago"
 *   < 24h      → "<N>h ago"
 *   < 7d       → "<N>d ago"
 *   < same yr  → "<dd> <Mon>"        (e.g. "24 Apr")
 *   otherwise  → "<dd> <Mon> <YYYY>" (e.g. "24 Apr 2024")
 *
 * `null` / `undefined` render as an em-dash so callers don't guard.
 * Used on the contacts list (and roll-out to leads / walk-ins /
 * appointments / tasks) for the `last_activity_at` column.
 */
@Pipe({ name: 'relativeTime', standalone: true })
export class RelativeTimePipe implements PipeTransform {
  transform(value: string | Date | null | undefined): string {
    if (value === null || value === undefined || value === '') return '—';
    const then = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(then.getTime())) return '—';

    const now = new Date();
    const diffMs = now.getTime() - then.getTime();
    const sec = Math.floor(diffMs / 1000);

    if (sec < 60) return 'just now';
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
    if (sec < 86400 * 7) return `${Math.floor(sec / 86400)}d ago`;

    const day = then.getDate();
    const month = then.toLocaleString('en-GB', { month: 'short' });
    if (then.getFullYear() === now.getFullYear()) {
      return `${day} ${month}`;
    }
    return `${day} ${month} ${then.getFullYear()}`;
  }
}
