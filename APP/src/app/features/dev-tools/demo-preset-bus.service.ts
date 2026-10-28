import { Injectable, signal } from '@angular/core';

import { DemoPreset } from './demo-presets';

/**
 * Root-provided bus that decouples the floating dev pill from the login
 * form. The pill calls `apply(preset)` from wherever in the app the
 * developer happens to be; the login form's effect reacts and patches
 * its FormGroup. Survives router navigation since it lives at the root
 * injector.
 */
@Injectable({ providedIn: 'root' })
export class DemoPresetBusService {
  private readonly _presets = signal<readonly DemoPreset[]>([]);
  readonly presets = this._presets.asReadonly();

  private readonly _selected = signal<DemoPreset | null>(null);
  readonly selected = this._selected.asReadonly();

  setPresets(presets: readonly DemoPreset[]): void {
    this._presets.set(presets);
  }

  apply(preset: DemoPreset): void {
    this._selected.set(preset);
  }

  clear(): void {
    this._selected.set(null);
  }
}
