/**
 * Inbound Addresses tab — Prativani-style inline 4-step setup.
 *
 * Row expansion hosts a 4-step stepper (Copy → Add at provider →
 * Confirm → Test) inline — no modal. Each row tracks its own step +
 * chosen provider. Step 4 polls the backend for the first inbound
 * arrival; when the poll returns ``'received'`` the row's ``last_inbound_at``
 * is populated on reload and the stepper collapses into a "Verified"
 * summary.
 *
 * The inline "Add an email address" card at the top is unchanged —
 * it's the single row-creation entry point. The old
 * :class:`ForwardingWizardComponent` modal is removed; the duplicate
 * row it used to create is no longer possible.
 */
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  OnDestroy,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { Subscription } from 'rxjs';
import { extractApiError } from '@core/services/api-error.util';

import { ConfirmDialogService } from '../../shared/confirm-dialog/confirm-dialog.service';
import { ToastService } from '../../../../../shared/components/toast/toast.service';
import type { ForwardedAddress } from './models';
import { InboundAddressesService } from './inbound-addresses.service';
import { PROVIDER_GUIDES, PROVIDER_ORDER, type ProviderGuide } from './provider-guides';
import { TestInboundStatusService, type PollTick } from './test-inbound-status.service';

/** Providers whose ToS forbid sending mail on their users' behalf
 * (SPF/DKIM won't authorise us). We surface this to the operator so
 * they don't waste time trying to configure "send as you" for a gmail
 * address. Domain-match is case-insensitive. */
const FREE_PROVIDER_DOMAINS = new Set([
  'gmail.com',
  'googlemail.com',
  'outlook.com',
  'hotmail.com',
  'live.com',
  'msn.com',
  'yahoo.com',
  'yahoo.co.uk',
  'yahoo.in',
  'ymail.com',
  'icloud.com',
  'me.com',
  'aol.com',
  'protonmail.com',
  'proton.me',
  'zoho.com',
]);

interface ParsedLabel {
  display: string;
  email: string;
}

export type WizardStep = 1 | 2 | 3 | 4;

const DEFAULT_PROVIDER_KEY = 'gmail';

@Component({
  selector: 'app-inbound-addresses-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule],
  templateUrl: './inbound-addresses-tab.component.html',
})
export class InboundAddressesTabComponent implements OnDestroy {
  private readonly api = inject(InboundAddressesService);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder);
  private readonly confirmDialog = inject(ConfirmDialogService);
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly poll = inject(TestInboundStatusService);

  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly addresses = signal<ForwardedAddress[]>([]);

  /** Row-id currently in the middle of a PATCH / DELETE. */
  readonly busyId = signal<string | null>(null);

  /** Inline "Add address" card — always visible when open. */
  readonly addFormOpen = signal(true);
  readonly creating = signal(false);

  /** Which row's inline setup panel is expanded. */
  readonly expandedId = signal<string | null>(null);

  /** Which row's 3-dot overflow menu is open. */
  readonly openMenuId = signal<string | null>(null);

  /** Per-row step in the inline 4-step setup flow. Defaults to 1. */
  readonly rowStep = signal<Record<string, WizardStep>>({});

  /** Per-row selected provider (key into PROVIDER_GUIDES). Defaults to 'gmail'. */
  readonly rowProvider = signal<Record<string, string>>({});

  /** Latest poll tick per row for step 4 status display. */
  readonly rowPollTick = signal<Record<string, PollTick>>({});

  readonly providerOrder = PROVIDER_ORDER;
  readonly guides = PROVIDER_GUIDES;

  private _pollSubs = new Map<string, Subscription>();

  protected readonly addForm = {
    email: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.required, Validators.email, Validators.maxLength(254)],
    }) as FormControl<string>,
    display: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.maxLength(128)],
    }) as FormControl<string>,
  };

  readonly sortedAddresses = computed<ReadonlyArray<ForwardedAddress>>(() => {
    const rows = this.addresses();
    const active = rows.filter((r) => r.is_active);
    const inactive = rows.filter((r) => !r.is_active);
    return [...active, ...inactive];
  });

  readonly hasPendingReceiver = computed(() => {
    return this.addresses().some((r) => r.is_active && !r.last_inbound_at);
  });

  readonly pendingReceiverCount = computed(() => {
    return this.addresses().filter((r) => r.is_active && !r.last_inbound_at).length;
  });

  constructor() {
    this.reload();
  }

  ngOnDestroy(): void {
    for (const sub of this._pollSubs.values()) sub.unsubscribe();
    this._pollSubs.clear();
  }

  reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.list().subscribe({
      next: (rows) => {
        this.addresses.set(rows);
        this.loading.set(false);
        for (const row of rows) {
          if (row.last_inbound_at) this._stopPolling(row.id);
        }
      },
      error: (err) => {
        this.loadError.set(extractApiError(err) ?? 'Could not load inbound addresses.');
        this.loading.set(false);
      },
    });
  }

  // --- Add form ------------------------------------------------------

  toggleAddForm(): void {
    this.addFormOpen.update((v) => !v);
    if (this.addFormOpen()) {
      this.addForm.email.reset('');
      this.addForm.display.reset('');
    }
  }

  cancelAdd(): void {
    if (this.creating()) return;
    this.addForm.email.reset('');
    this.addForm.display.reset('');
  }

  submitAdd(): void {
    if (this.creating()) return;
    if (this.addForm.email.invalid) {
      this.addForm.email.markAsTouched();
      return;
    }
    const email = (this.addForm.email.value || '').trim().toLowerCase();
    const display = (this.addForm.display.value || '').trim();
    const label = this._formatLabel(display, email);
    this.creating.set(true);
    this.api.create({ label }).subscribe({
      next: (row) => {
        this.addresses.update((current) => [row, ...current]);
        this.expandedId.set(row.id);
        this.addForm.email.reset('');
        this.addForm.display.reset('');
        this.creating.set(false);
        this.toast.success('Address added. Copy the forwarding address below.');
      },
      error: (err) => {
        this.creating.set(false);
        this.toast.error(extractApiError(err) ?? 'Could not add address.');
      },
    });
  }

  // --- Row actions ---------------------------------------------------

  toggleExpanded(id: string): void {
    const wasOpen = this.expandedId() === id;
    this.expandedId.update((current) => (current === id ? null : id));
    if (wasOpen && this.stepFor(id) === 4) this._stopPolling(id);
  }

  toggleOverflowMenu(id: string): void {
    this.openMenuId.update((current) => (current === id ? null : id));
  }

  /** Close the overflow menu on outside click. */
  @HostListener('document:mousedown', ['$event.target'])
  onDocumentClick(target: EventTarget | null): void {
    if (!this.openMenuId()) return;
    if (!(target instanceof Node)) {
      this.openMenuId.set(null);
      return;
    }
    if (!this.host.nativeElement.contains(target)) {
      this.openMenuId.set(null);
    }
  }

  async copyAddress(row: ForwardedAddress): Promise<void> {
    if (!row.forwarding_address) return;
    await navigator.clipboard.writeText(row.forwarding_address);
    this.toast.success(`Copied ${row.forwarding_address}`);
  }

  toggleAutoCreate(row: ForwardedAddress): void {
    this.busyId.set(row.id);
    const next = !row.auto_create_contact;
    this.api.update(row.id, { auto_create_contact: next }).subscribe({
      next: (updated) => {
        this._replaceRow(updated);
        this.busyId.set(null);
      },
      error: (err) => {
        this.busyId.set(null);
        this.toast.error(extractApiError(err) ?? 'Update failed.');
      },
    });
  }

  async deactivate(row: ForwardedAddress): Promise<void> {
    this.openMenuId.set(null);
    const parsed = this.parseLabel(row.label);
    const ok = await this.confirmDialog.ask({
      title: `Deactivate ${parsed.email}?`,
      body: `Mail arriving at ${row.forwarding_address} will stop reaching the CRM. You can reactivate this address later without losing the token.`,
      confirmLabel: 'Deactivate',
      cancelLabel: 'Keep it',
      danger: true,
    });
    if (!ok) return;
    this.busyId.set(row.id);
    this.api.deactivate(row.id).subscribe({
      next: () => {
        this.busyId.set(null);
        this.toast.success(`${parsed.email} deactivated.`);
        this.reload();
      },
      error: (err) => {
        this.busyId.set(null);
        this.toast.error(extractApiError(err) ?? 'Deactivation failed.');
      },
    });
  }

  async remove(row: ForwardedAddress): Promise<void> {
    this.openMenuId.set(null);
    const parsed = this.parseLabel(row.label);
    const ok = await this.confirmDialog.ask({
      title: `Delete ${parsed.email}?`,
      body: `Any mail arriving at ${row.forwarding_address} after deletion won't reach the CRM. Historical messages on the conversation stay intact. This cannot be undone.`,
      confirmLabel: 'Delete',
      cancelLabel: 'Keep it',
      danger: true,
    });
    if (!ok) return;
    this.busyId.set(row.id);
    this.api.remove(row.id).subscribe({
      next: () => {
        this.busyId.set(null);
        this.toast.success(`${parsed.email} deleted.`);
        this._stopPolling(row.id);
        this.reload();
      },
      error: (err) => {
        this.busyId.set(null);
        this.toast.error(extractApiError(err) ?? 'Delete failed.');
      },
    });
  }

  // --- Inline stepper -------------------------------------------------

  stepFor(rowId: string): WizardStep {
    return this.rowStep()[rowId] ?? 1;
  }

  providerKeyFor(rowId: string): string {
    return this.rowProvider()[rowId] ?? DEFAULT_PROVIDER_KEY;
  }

  guideFor(rowId: string): ProviderGuide {
    return this.guides[this.providerKeyFor(rowId)];
  }

  pickRowProvider(rowId: string, key: string): void {
    if (!this.guides[key]) return;
    this.rowProvider.update((current) => ({ ...current, [rowId]: key }));
  }

  advanceStep(rowId: string): void {
    const current = this.stepFor(rowId);
    if (current >= 4) return;
    const next = (current + 1) as WizardStep;
    this.rowStep.update((c) => ({ ...c, [rowId]: next }));
    if (next === 4) this._startPolling(rowId);
  }

  backStep(rowId: string): void {
    const current = this.stepFor(rowId);
    if (current <= 1) return;
    if (current === 4) this._stopPolling(rowId);
    const prev = (current - 1) as WizardStep;
    this.rowStep.update((c) => ({ ...c, [rowId]: prev }));
  }

  goToStep(rowId: string, step: WizardStep): void {
    if (step < 1 || step > 4) return;
    const wasStep4 = this.stepFor(rowId) === 4;
    this.rowStep.update((c) => ({ ...c, [rowId]: step }));
    if (step === 4 && !wasStep4) this._startPolling(rowId);
    if (step !== 4 && wasStep4) this._stopPolling(rowId);
  }

  pollTickFor(rowId: string): PollTick | null {
    return this.rowPollTick()[rowId] ?? null;
  }

  private _startPolling(rowId: string): void {
    this._stopPolling(rowId);
    const sub = this.poll.poll(rowId).subscribe({
      next: (tick) => {
        this.rowPollTick.update((c) => ({ ...c, [rowId]: tick }));
        if (tick.kind === 'received') {
          this.toast.success('Test email received. Setup verified.');
          this.reload();
        }
      },
    });
    this._pollSubs.set(rowId, sub);
  }

  private _stopPolling(rowId: string): void {
    const sub = this._pollSubs.get(rowId);
    if (sub) {
      sub.unsubscribe();
      this._pollSubs.delete(rowId);
    }
  }

  // --- Label parsing --------------------------------------------------

  parseLabel(label: string): ParsedLabel {
    const trimmed = (label || '').trim();
    const m = trimmed.match(/^(.*?)\s*<([^<>]+)>\s*$/);
    if (m) {
      const rawDisplay = m[1].trim().replace(/^["']|["']$/g, '');
      return { display: rawDisplay, email: m[2].trim() };
    }
    return { display: '', email: trimmed };
  }

  private _formatLabel(display: string, email: string): string {
    if (!display) return email;
    const needsQuote = /[",<>@]/.test(display);
    const safeDisplay = needsQuote ? `"${display.replace(/"/g, '\\"')}"` : display;
    return `${safeDisplay} <${email}>`;
  }

  isFreeProvider(row: ForwardedAddress): boolean {
    const domain = this.parseLabel(row.label).email.split('@')[1]?.toLowerCase();
    return !!domain && FREE_PROVIDER_DOMAINS.has(domain);
  }

  freeProviderDomain(row: ForwardedAddress): string {
    const domain = this.parseLabel(row.label).email.split('@')[1]?.toLowerCase();
    return domain ?? '';
  }

  // --- Formatting -----------------------------------------------------

  lastInboundLabel(iso: string | null): string {
    if (!iso) return 'No mail yet';
    const then = new Date(iso).getTime();
    const delta = Math.max(0, Date.now() - then);
    const mins = Math.floor(delta / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  private _replaceRow(updated: ForwardedAddress): void {
    this.addresses.update((current) => current.map((r) => (r.id === updated.id ? updated : r)));
  }
}
