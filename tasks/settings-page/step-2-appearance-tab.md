# Step 2 — Appearance tab: light / dark / system theme picker

**Status:** COMPLETED — `ThemeService` extended with a `ThemeChoice` type (`'light' | 'dark' | 'system'`), a `choice` signal, an explicit `set()` method, and a `matchMedia('(prefers-color-scheme: dark)')` listener that re-applies the theme live when the user has chosen `'system'` and flips their OS preference. Legacy `toggle()` / `isDark()` / `getTheme()` retained so the admin + accounts layout buttons keep working — `toggle()` now persists an explicit `'light'`/`'dark'` choice instead of letting `'system'` linger. New `AppearanceTabComponent` registers as the second tab (no permission gate); template renders three preview cards (Light = white swatch, Dark = zinc-900 swatch, System = white→zinc-900 gradient). 5 files (2 new + 3 modified).

**Goal:** Surface the existing `ThemeService` as a Settings tab. Three-way radio: **Light · Dark · System**. Persists via the existing `localStorage` key (`STORAGE_KEY_THEME`). Pure frontend — no backend.

**Depends on:** Step 1 (Profile tab; this sits next to it as the second personal tab).

## Why this step exists

`ThemeService` already exists at `APP/src/app/core/services/theme.service.ts` and is initialized in `app.config.ts`. It can toggle Light ↔ Dark and persists to `localStorage`. Today there's no UI to actually pick — staff are stuck on whatever was applied at first load (system preference). A one-control tab fixes that without any backend work and gives Employees a useful self-service toggle.

## Files changed

### New
- `APP/src/app/features/user/core/settings/tabs/appearance-tab.component.ts`
- `APP/src/app/features/user/core/settings/tabs/appearance-tab.component.html`

### Modified
- `APP/src/app/features/user/core/settings/settings-page.component.ts` — register tab.
- `APP/src/app/features/user/core/settings/settings-page.component.html` — add `@case ('appearance')` branch.
- `APP/src/app/core/services/theme.service.ts` — small extension: add `set(theme: 'light' | 'dark' | 'system')` so the radio can pick "system" explicitly (today's `toggle()` only flips Light/Dark and `init()` does the system-pref read).

### Tests
- Browser smoke only.

## `theme.service.ts` extension

Add a `set()` method that handles the three explicit choices and a `current` signal so the component can bind:

```ts
import { Injectable, signal } from '@angular/core';
// ... existing imports ...

export type ThemeChoice = 'light' | 'dark' | 'system';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  // ... existing private fields ...

  /** User's saved choice — 'system' means "follow OS preference."
   *  Defaults to 'system' so first-load matches today's behavior. */
  readonly choice = signal<ThemeChoice>('system');

  init(): void {
    const saved = (localStorage.getItem(STORAGE_KEY_THEME) as ThemeChoice | null)
      ?? 'system';
    this.choice.set(saved);
    this.applyResolved(saved);
  }

  set(choice: ThemeChoice): void {
    this.choice.set(choice);
    localStorage.setItem(STORAGE_KEY_THEME, choice);
    this.applyResolved(choice);
  }

  private applyResolved(choice: ThemeChoice): void {
    const effective = choice === 'system'
      ? this.getSystemPreference()
      : (choice === 'dark' ? THEME_DARK : THEME_LIGHT);
    this.applyTheme(effective);
  }

  // ... existing applyTheme / setStylesheetEnabled / getSystemPreference unchanged
}
```

Keep `toggle()` and `getTheme()` for back-compat with any existing callers; the new `choice` signal + `set()` are the surface the new tab uses.

## `appearance-tab.component.ts`

```ts
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ThemeService, ThemeChoice } from '@core/services/theme.service';

@Component({
  selector: 'app-settings-appearance-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  templateUrl: './appearance-tab.component.html',
})
export class AppearanceTabComponent {
  private readonly theme = inject(ThemeService);

  protected readonly choice = this.theme.choice;

  protected pick(c: ThemeChoice): void {
    this.theme.set(c);
  }
}
```

## `appearance-tab.component.html`

Three radio cards with previews. Tailwind only — no PrimeNG.

```html
<div>
  <p class="mb-4 text-sm text-zinc-500">
    Choose how the app looks. <b>System</b> follows your operating-system preference and updates automatically when you switch.
  </p>

  <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
    @for (opt of options; track opt.id) {
      <button
        type="button"
        (click)="pick(opt.id)"
        class="rounded-lg border p-4 text-left transition"
        [class.border-zinc-900]="choice() === opt.id"
        [class.bg-zinc-50]="choice() === opt.id"
        [class.border-zinc-200]="choice() !== opt.id"
      >
        <div class="mb-2 h-16 rounded-md border"
             [class.bg-white]="opt.preview === 'light'"
             [class.bg-zinc-900]="opt.preview === 'dark'"
             [class.bg-gradient-to-r]="opt.preview === 'system'"
             [class.from-white]="opt.preview === 'system'"
             [class.to-zinc-900]="opt.preview === 'system'">
        </div>
        <div class="text-sm font-medium text-zinc-900">{{ opt.label }}</div>
        <div class="text-xs text-zinc-500">{{ opt.hint }}</div>
      </button>
    }
  </div>
</div>
```

With `options` declared on the component:

```ts
protected readonly options = [
  { id: 'light' as const,  label: 'Light',  hint: 'Always bright',     preview: 'light' },
  { id: 'dark' as const,   label: 'Dark',   hint: 'Always dim',        preview: 'dark' },
  { id: 'system' as const, label: 'System', hint: 'Match your OS',     preview: 'system' },
];
```

## Permission gate

None — purely personal preference.

## Tests

Browser smoke:
1. Open Settings → Appearance tab.
2. Pick Dark → app instantly switches; reload → still Dark.
3. Pick System → app switches to match OS pref; toggle OS dark mode → confirm app follows.

## Acceptance

- Three radio cards visible in tab.
- Selection persists across reloads.
- "System" follows OS preference.
- Default for new users = System (matches today's behavior).

## Self-check vs the 10 rules

- ✅ Rule 5, 6 — no module / permission changes.
- ✅ Rule 8 — 5 files; under limit.
- ✅ Rule 10 — ships complete; no half-shipped theme states.

## Stop-and-report template

> ✅ Step 2 complete.
> **Files changed:** 5 (2 new, 3 modified).
> **What you can verify:**
> 1. Settings → Appearance shows three theme cards.
> 2. Switching theme is instant and persists.
> 3. System option follows OS dark-mode toggle.
> **Tests added:** browser smoke only.
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 3.
