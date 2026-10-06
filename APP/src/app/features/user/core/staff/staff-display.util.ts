/**
 * Display helpers shared by the Staff Dashboard tabs (Overview,
 * Leaderboard, Targets) so the same status badge and progress colours
 * render everywhere. Pure functions — no DI, no state.
 */

/** Employment-status pill. `null` = the user has no staff profile yet. */
export function employmentStatusBadge(status: string | null): { label: string; cls: string } {
  switch (status) {
    case 'active':
      return { label: 'Active', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200' };
    case 'leave':
      return { label: 'On Leave', cls: 'bg-amber-50 text-amber-700 ring-amber-200' };
    case 'terminated':
      return { label: 'Off-boarded', cls: 'bg-red-500/10 text-red-400 ring-red-500/20' };
    default:
      return { label: 'No profile', cls: 'bg-surface-2 text-muted ring-subtle' };
  }
}

/** Progress-bar fill colour by how close someone is to target:
 *  red under 40%, amber under 80%, green from 80% (incl. exceeded). */
export function progressTone(pct: number | null): string {
  if (pct === null) return 'bg-zinc-400';
  if (pct < 40) return 'bg-red-500';
  if (pct < 80) return 'bg-amber-500';
  return 'bg-emerald-500';
}

/** Bar width in %, clamped to 0–100 (a 140% achiever fills the bar). */
export function progressWidth(pct: number | null): number {
  if (pct === null || pct < 0) return 0;
  return pct > 100 ? 100 : pct;
}

/** Converted share of all leads a rep has touched, or null when none. */
export function conversionPct(converted: number, active: number): number | null {
  const total = converted + active;
  return total === 0 ? null : Math.round((converted / total) * 100);
}
