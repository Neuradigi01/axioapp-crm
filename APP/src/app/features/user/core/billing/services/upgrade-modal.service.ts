import { Injectable, signal } from '@angular/core';

import { BillingCycle } from '../types/subscription.types';

/** Optional pre-fill hints when opening the upgrade modal. */
export interface UpgradeModalOpenOptions {
  /** Pre-select this plan code on the radio cards. */
  plan?: string;
  /** Pre-select this billing cycle on the toggle. */
  cycle?: BillingCycle;
  /** Pre-fill the seat counter. Defaults to `max(included, in_use)`
   *  inside the modal when omitted. */
  seats?: number;
}

interface UpgradeModalState {
  open: boolean;
  initialPlan: string | null;
  initialCycle: BillingCycle | null;
  initialSeats: number | null;
}

const CLOSED_STATE: UpgradeModalState = {
  open: false,
  initialPlan: null,
  initialCycle: null,
  initialSeats: null,
};

/**
 * Imperative open/close API for the upgrade modal.
 *
 * The modal component lives in the global shell (`shell.component.html`)
 * and renders nothing when `open()` returns `false`. Callers in
 * scattered parts of the UI (trial banner, billing page buttons,
 * locked-feature tile in Step 18) inject this service and call
 * `open({...prefill})` to surface the modal without owning its
 * lifecycle.
 *
 * `providedIn: 'root'` so the state is shared globally. Multiple
 * instances would split the open/close state and the shell-mounted
 * modal would never react to a sibling component's open call.
 */
@Injectable({ providedIn: 'root' })
export class UpgradeModalService {
  private readonly _state = signal<UpgradeModalState>(CLOSED_STATE);

  readonly state = this._state.asReadonly();

  open(options: UpgradeModalOpenOptions = {}): void {
    this._state.set({
      open: true,
      initialPlan: options.plan ?? null,
      initialCycle: options.cycle ?? null,
      initialSeats: options.seats ?? null,
    });
  }

  close(): void {
    this._state.set(CLOSED_STATE);
  }
}
