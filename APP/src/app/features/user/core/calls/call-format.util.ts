import { format } from 'date-fns';

/** "5 Oct, 4:32 PM" — year added only when it isn't the current one. */
export function formatCallTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return format(d, sameYear ? 'd MMM, h:mm a' : 'd MMM yyyy, h:mm a');
}

/** "2m 5s" / "45s". */
export function formatCallDuration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}
