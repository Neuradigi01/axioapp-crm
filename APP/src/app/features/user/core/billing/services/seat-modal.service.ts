import { Injectable, signal } from '@angular/core';

interface SeatModalState {
  open: boolean;
}

const CLOSED: SeatModalState = { open: false };

/**
 * Open/close API for the seat-management modal.
 *
 * Lighter than `UpgradeModalService` because the seat modal needs no
 * prefill — it always reads the current subscription's seats and
 * lets the user nudge the count up or down.
 *
 * `providedIn: 'root'` so the state is shared between the trigger
 * (Billing settings page's "Manage seats" button) and the modal
 * mounted inside `billing.page.html`.
 */
@Injectable({ providedIn: 'root' })
export class SeatModalService {
  private readonly _state = signal<SeatModalState>(CLOSED);
  readonly state = this._state.asReadonly();

  open(): void {
    this._state.set({ open: true });
  }

  close(): void {
    this._state.set(CLOSED);
  }
}
