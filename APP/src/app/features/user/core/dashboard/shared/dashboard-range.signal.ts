/**
 * Shared writable signal for the dashboard's selected date range.
 *
 * Module-scoped on purpose: every dashboard widget lives on the same
 * route and observes the same range. Persisted to `localStorage` so a
 * full reload restores the user's last choice; SSR / private-mode
 * `localStorage` failures degrade to the in-memory default.
 *
 * If the signal ever needs to be shared across routes, lift it into an
 * injectable service — for now the simple module export is enough.
 */
import { signal } from '@angular/core';

export type DashboardRange = '7d' | '30d' | '90d' | '365d';

const STORAGE_KEY = 'crm.dashboard.range';
const DEFAULT_RANGE: DashboardRange = '30d';
const VALID: ReadonlySet<DashboardRange> = new Set(['7d', '30d', '90d', '365d']);

function loadInitial(): DashboardRange {
  if (typeof localStorage === 'undefined') return DEFAULT_RANGE;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && VALID.has(stored as DashboardRange)) {
      return stored as DashboardRange;
    }
  } catch {
    // private mode / disabled storage — fall through to default
  }
  return DEFAULT_RANGE;
}

export const dashboardRange = signal<DashboardRange>(loadInitial());

export function setDashboardRange(next: DashboardRange): void {
  dashboardRange.set(next);
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // private mode — signal still updates, just won't survive reload
  }
}
