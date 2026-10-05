import { Signal, computed, inject } from '@angular/core';

import { ThemeService } from '@core/services/theme.service';

/** Theme colours for ApexCharts, which paints SVG with literal colour
 *  strings and so never sees the CSS tokens on its own. */
export interface ChartTheme {
  dark: boolean;
  /** Series colour — the org accent. */
  accent: string;
  /** Axis label colour. */
  text: string;
  /** Grid line colour. */
  grid: string;
}

/**
 * Reads the live theme tokens and recomputes when the user changes the
 * theme choice. Call from a component field initializer (needs an
 * injection context).
 */
export function injectChartTheme(): Signal<ChartTheme> {
  const theme = inject(ThemeService);
  return computed(() => {
    theme.choice();
    const root = document.documentElement;
    const css = getComputedStyle(root);
    const token = (name: string, fallback: string): string =>
      css.getPropertyValue(name).trim() || fallback;
    return {
      dark: root.getAttribute('data-theme') === 'dark',
      accent: token('--accent', '#0d9488'),
      text: token('--text-muted', '#667085'),
      grid: token('--border', '#e4e7ec'),
    };
  });
}

/** `#rrggbb` + alpha (0–1) → `#rrggbbaa`; other formats pass through. */
export function withAlpha(hex: string, alpha: number): string {
  if (!/^#[0-9a-fA-F]{6}$/.test(hex)) return hex;
  const a = Math.round(Math.min(1, Math.max(0, alpha)) * 255)
    .toString(16)
    .padStart(2, '0');
  return `${hex}${a}`;
}
