import { Injectable, signal } from '@angular/core';

/**
 * Lightweight event bus for "an org-level standard-field override was
 * just saved or reset". Form modals (Steps 5/6) subscribe via
 *
 *   effect(() => {
 *     this.signals.changedAt();   // creates the dependency
 *     this.refetchFields();
 *   });
 *
 * and refetch their `/render` response. The numeric timestamp is bumped
 * (not toggled) so consecutive saves of the same field still fire.
 *
 * Root-provided — every modal must see the same instance.
 */
@Injectable({ providedIn: 'root' })
export class StandardFieldsSignalsService {
  /** Bumped to `Date.now()` after every successful PUT or DELETE. */
  readonly changedAt = signal<number>(0);

  /** Call from the Settings tab after a save succeeds. */
  notifyChange(): void {
    this.changedAt.set(Date.now());
  }
}
