import { Injectable } from '@angular/core';
import { Theme } from '@app/schemas/common';
import { STORAGE_KEY_THEME, THEME_LIGHT, THEME_DARK } from '@core/constants/app.constants';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private currentTheme: Theme = THEME_LIGHT;

  init(): void {
    const saved = localStorage.getItem(STORAGE_KEY_THEME) as Theme | null;
    const preferred = saved ?? this.getSystemPreference();
    this.applyTheme(preferred);
  }

  toggle(): void {
    this.applyTheme(this.currentTheme === THEME_LIGHT ? THEME_DARK : THEME_LIGHT);
  }

  getTheme(): Theme {
    return this.currentTheme;
  }

  isDark(): boolean {
    return this.currentTheme === THEME_DARK;
  }

  private applyTheme(theme: Theme): void {
    this.currentTheme = theme;
    localStorage.setItem(STORAGE_KEY_THEME, theme);

    this.setStylesheetEnabled(THEME_LIGHT, theme === THEME_LIGHT);
    this.setStylesheetEnabled(THEME_DARK, theme === THEME_DARK);

    document.body.classList.remove('light-theme', 'dark-theme');
    document.body.classList.add(`${theme}-theme`);
  }

  private setStylesheetEnabled(bundleName: string, enabled: boolean): void {
    let link = document.querySelector(
      `link[rel="stylesheet"][href*="${bundleName}"]`
    ) as HTMLLinkElement | null;

    if (!link && enabled) {
      link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = `${bundleName}.css`;
      document.head.appendChild(link);
    }

    if (link) {
      link.disabled = !enabled;
    }
  }

  private getSystemPreference(): Theme {
    return window.matchMedia('(prefers-color-scheme: dark)').matches
      ? THEME_DARK
      : THEME_LIGHT;
  }
}
