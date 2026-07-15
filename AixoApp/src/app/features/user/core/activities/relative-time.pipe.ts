import { Pipe, PipeTransform } from '@angular/core';

/**
 * Short, human-readable relative-time string for a past timestamp.
 *
 *   < 45 s          → "just now"
 *   < 60 min        → "X min ago"
 *   < 24 h          → "X h ago"
 *   < 7 days        → "X d ago"
 *   else            → localized date ("12 May 2026")
 *
 * Future timestamps fall back to "just now" rather than going negative —
 * timeline rows are always backward-looking by definition.
 *
 * Marked `pure: true` (the Angular default) so it does not re-run on
 * every change-detection tick — the input string is stable per row.
 */
@Pipe({ name: 'relativeTime', standalone: true })
export class RelativeTimePipe implements PipeTransform {
  transform(value: string | Date | null | undefined): string {
    if (value === null || value === undefined || value === '') return '';
    const then = value instanceof Date ? value.getTime() : Date.parse(value);
    if (Number.isNaN(then)) return '';

    const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
    if (seconds < 45) return 'just now';

    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} min ago`;

    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} h ago`;

    const days = Math.floor(hours / 24);
    if (days < 7) return `${days} d ago`;

    return new Date(then).toLocaleDateString(undefined, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  }
}
