/**
 * Inbound Addresses tab (Prativani-style redesign).
 *
 * Layout matches the reference:
 *   * Inline **"Add an email address"** card at the top — Email +
 *     Display name inputs, Cancel / Add address buttons. No modal for
 *     creation.
 *   * A **"Not receiving yet"** banner appears while any active row's
 *     forwarding rule hasn't fired yet (``last_inbound_at`` is null).
 *   * Each row card shows the display name in bold + the raw email in
 *     muted mono, with a 3-dot overflow menu on the right.
 *   * An **expandable "Receiving · Setting up"** panel per row that
 *     surfaces the copy-your-forwarding-address step inline. Continue
 *     opens the shipped :class:`ForwardingWizardComponent` modal for
 *     the multi-step provider guide.
 *   * A **"SEND AS YOU"** info block below the setup panel that
 *     detects free providers (gmail.com / outlook.com / yahoo.com /
 *     ...) and explains why send-as-you isn't available for them.
 *
 * Backend contract unchanged: ``label`` still stores the composite
 * ``"Display Name <email>"`` (or bare email when no display name),
 * matching the RFC-5322 ``mailbox`` shape the ingest side already
 * parses. All existing ``ForwardedAddress`` rows keep working — the
 * parser gracefully falls back to treating the whole label as an
 * email when it can't split.
 */
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { extractApiError } from '@core/services/api-error.util';

import { ConfirmDialogService } from '../../shared/confirm-dialog/confirm-dialog.service';
import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { ForwardingWizardComponent } from './forwarding-wizard.component';
import type { ForwardedAddress } from './models';
import { InboundAddressesService } from './inbound-addresses.service';

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

@Component({
  selector: 'app-inbound-addresses-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ForwardingWizardComponent, LucideAngularModule, ReactiveFormsModule],
  templateUrl: './inbound-addresses-tab.component.html',
})
export class InboundAddressesTabComponent {
  private readonly api = inject(InboundAddressesService);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder);
  private readonly confirmDialog = inject(ConfirmDialogService);
  private readonly host = inject(ElementRef<HTMLElement>);

  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly addresses = signal<ForwardedAddress[]>([]);

  /** Row-id currently in the middle of a PATCH / DELETE — powers the
   * per-row spinner + disables its action buttons. */
  readonly busyId = signal<string | null>(null);

  /** True while the deep multi-step wizard modal is mounted. Launched
   *  from the inline "Continue" button when the operator's ready to
   *  set up the forwarding rule at their provider. */
  readonly showWizard = signal(false);

  /** Inline "Add address" card — always visible when open. */
  readonly addFormOpen = signal(true);
  readonly creating = signal(false);

  /** Which row's inline "Setting up" panel is expanded. Freshly-created
   *  rows open by default (``expandedId`` set on create); users toggle
   *  after the first inbound arrives. */
  readonly expandedId = signal<string | null>(null);

  /** Which row's 3-dot overflow menu is open. */
  readonly openMenuId = signal<string | null>(null);

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

  /** True when at least one active row hasn't received any mail yet —
   *  drives the "Not receiving yet · One address is waiting on its
   *  forwarding rule" banner Prativani shows above the list. */
  readonly hasPendingReceiver = computed(() => {
    return this.addresses().some((r) => r.is_active && !r.last_inbound_at);
  });

  readonly pendingReceiverCount = computed(() => {
    return this.addresses().filter((r) => r.is_active && !r.last_inbound_at).length;
  });

  constructor() {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.list().subscribe({
      next: (rows) => {
        this.addresses.set(rows);
        this.loading.set(false);
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
    // Match Prativani: cancel just resets, doesn't collapse the card.
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
    this.expandedId.update((current) => (current === id ? null : id));
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

  /** Mount the shipped Step-6 3-step wizard for the multi-step guide. */
  continueWizard(row: ForwardedAddress): void {
    void row;
    this.openMenuId.set(null);
    this.showWizard.set(true);
  }

  onWizardClose(): void {
    this.showWizard.set(false);
    this.reload();
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
        this.reload();
      },
      error: (err) => {
        this.busyId.set(null);
        this.toast.error(extractApiError(err) ?? 'Delete failed.');
      },
    });
  }

  // --- Label parsing --------------------------------------------------

  /** Split a stored ``label`` into ``{display, email}``. Handles both
   *  RFC-5322 style ``"Display Name <email@x.com>"`` and the bare
   *  ``email@x.com`` form. Falls back to treating the whole string as
   *  the email when no ``<...>`` block is present. */
  parseLabel(label: string): ParsedLabel {
    const trimmed = (label || '').trim();
    const m = trimmed.match(/^(.*?)\s*<([^<>]+)>\s*$/);
    if (m) {
      const rawDisplay = m[1].trim().replace(/^["']|["']$/g, '');
      return { display: rawDisplay, email: m[2].trim() };
    }
    return { display: '', email: trimmed };
  }

  /** Inverse of :func:`parseLabel`. */
  private _formatLabel(display: string, email: string): string {
    if (!display) return email;
    const needsQuote = /[",<>@]/.test(display);
    const safeDisplay = needsQuote ? `"${display.replace(/"/g, '\\"')}"` : display;
    return `${safeDisplay} <${email}>`;
  }

  /** True when the address's email domain is a free consumer provider. */
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
