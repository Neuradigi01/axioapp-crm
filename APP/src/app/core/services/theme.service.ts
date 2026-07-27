import { Injectable, signal } from '@angular/core';
import { Theme } from '@app/schemas/common';
import { STORAGE_KEY_THEME, THEME_LIGHT, THEME_DARK } from '@core/constants/app.constants';

/**
 * User-facing theme choice. `'system'` means "follow the OS preference
 * and update live when it changes." The applied (effective) theme is
 * always `Theme` ('light' | 'dark') — `'system'` resolves to one or the
 * other at apply time and on `matchMedia` change.
 */
export type ThemeChoice = 'light' | 'dark' | 'system';

const THEME_SYSTEM: ThemeChoice = 'system';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private currentTheme: Theme = THEME_LIGHT;
  /** OS-preference listener; reapplies the theme on system flip when
   *  the user has chosen `'system'`. */
  private mediaQuery: MediaQueryList | null = null;
  private mediaListener: ((e: MediaQueryListEvent) => void) | null = null;

  /** User's saved choice — bound by the Settings → Appearance tab. */
  readonly choice = signal<ThemeChoice>(THEME_SYSTEM);

  init(): void {
    const saved = localStorage.getItem(STORAGE_KEY_THEME) as ThemeChoice | null;
    const choice: ThemeChoice = saved ?? THEME_SYSTEM;
    this.choice.set(choice);
    this.applyResolved(choice);
    this.bindSystemListener();
  }

  /** Set the explicit user choice. Persists and applies immediately. */
  set(choice: ThemeChoice): void {
    this.choice.set(choice);
    localStorage.setItem(STORAGE_KEY_THEME, choice);
    this.applyResolved(choice);
  }

  /** Legacy two-way toggle. Kept for the admin + accounts header
   *  toggle buttons; flips Light ↔ Dark and stores the explicit choice
   *  so it persists past `'system'`. */
  toggle(): void {
    this.set(this.currentTheme === THEME_LIGHT ? THEME_DARK : THEME_LIGHT);
  }

  /** Currently *applied* theme — always 'light' or 'dark'. */
  getTheme(): Theme {
    return this.currentTheme;
  }

  isDark(): boolean {
    return this.currentTheme === THEME_DARK;
  }

  private applyResolved(choice: ThemeChoice): void {
    const effective: Theme =
      choice === THEME_SYSTEM
        ? this.getSystemPreference()
        : choice === THEME_DARK
          ? THEME_DARK
          : THEME_LIGHT;
    this.applyTheme(effective);
  }

  private applyTheme(theme: Theme): void {
    this.currentTheme = theme;
    // Single source of truth: `[data-theme]` attribute on <html>.
    // Both `aixo-tokens.scss` and the legacy `light.scss` / `dark.scss`
    // (loaded together into styles.scss) key off this attribute.
    document.documentElement.setAttribute('data-theme', theme);
  }

  private getSystemPreference(): Theme {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? THEME_DARK : THEME_LIGHT;
  }

  private bindSystemListener(): void {
    if (this.mediaQuery || typeof window === 'undefined') return;
    this.mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    this.mediaListener = () => {
      if (this.choice() === THEME_SYSTEM) {
        this.applyResolved(THEME_SYSTEM);
      }
    };
    this.mediaQuery.addEventListener('change', this.mediaListener);
  }
}
