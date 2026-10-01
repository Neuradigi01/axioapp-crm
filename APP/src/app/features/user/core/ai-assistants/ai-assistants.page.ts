/**
 * AI Assistants list page (``tasks/ai-assistants`` Step 7).
 *
 * Layout mirrors the workflows / templates / campaigns list pages:
 * a header with title + create CTA + filter bar, and a grid of
 * assistant cards below. Status filter is a pill row; search is a
 * debounced text input (300ms) that maps to the backend's
 * ``?search=`` query param.
 *
 * "+ Create Assistant" opens :class:`CreateAssistantModalComponent`
 * which handles the two-field flow (name + key select) and, on
 * successful POST, navigates the caller into the editor for the
 * fresh row.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  HostListener,
  computed,
  inject,
  signal,
} from '@angular/core';
import { toObservable } from '@angular/core/rxjs-interop';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged, skip, switchMap, tap } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '@shared/components/toast/toast.service';
import { FurnitureAuthService } from '../auth/auth.service';
import {
  AiAssistant,
  AiAssistantListItem,
  AiAssistantStatus,
  AiAssistantsApiService,
} from './ai-assistants-api.service';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import { CreateAssistantModalComponent } from './create-assistant-modal.component';

interface StatusPill {
  value: '' | AiAssistantStatus;
  label: string;
  cls: string;
}

const STATUS_PILLS: StatusPill[] = [
  { value: '', label: 'All', cls: '' },
  { value: 'draft', label: 'Draft', cls: 'bg-surface-2 text-muted' },
  { value: 'active', label: 'Active', cls: 'bg-emerald-500/10 text-emerald-400' },
  { value: 'archived', label: 'Archived', cls: 'bg-surface-2 text-faint' },
];

const STATUS_BADGE: Record<AiAssistantStatus, { label: string; cls: string }> = {
  draft: { label: 'Draft', cls: 'bg-surface-2 text-muted ring-subtle' },
  active: { label: 'Active', cls: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20' },
  archived: { label: 'Archived', cls: 'bg-surface-2 text-faint ring-subtle' },
};

@Component({
  selector: 'app-ai-assistants-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, RouterLink, CreateAssistantModalComponent, ConfirmDialogComponent],
  templateUrl: './ai-assistants.page.html',
})
export class AiAssistantsPage {
  private readonly api = inject(AiAssistantsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);

  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly items = signal<AiAssistantListItem[]>([]);
  protected readonly total = signal(0);

  protected readonly statusFilter = signal<'' | AiAssistantStatus>('');
  protected readonly search = signal('');
  protected readonly modalOpen = signal(false);
  protected readonly kebabOpenId = signal<string | null>(null);
  // Row selected for delete via the kebab menu. When set, the shared
  // ConfirmDialogComponent renders — replaces the browser ``confirm()``
  // popup so the destructive-action prompt matches the rest of the UI
  // (title / body / red button / submitting state / inline error).
  protected readonly pendingDelete = signal<AiAssistantListItem | null>(null);
  // Row selected for archive/unarchive via the kebab menu. Mirrors the
  // pendingDelete pattern so the confirm dialog reuses the same UX
  // (styled modal instead of a raw window.confirm or silent fire).
  protected readonly pendingArchive = signal<AiAssistantListItem | null>(null);
  protected readonly pendingActivate = signal<AiAssistantListItem | null>(null);
  protected readonly actionInFlight = signal<string | null>(null);
  /** Failure of the confirm-dialog action — shown inside the dialog so
   *  the operator can retry or cancel with the context still visible. */
  protected readonly actionError = signal<string | null>(null);

  protected readonly statusPills = STATUS_PILLS;

  protected readonly canManage = computed(() =>
    this.auth.currentPermissions().includes('ai_assistants.manage'),
  );

  protected readonly emptyState = computed(
    () =>
      !this.loading() && this.items().length === 0 && this.statusFilter() === '' && !this.search(),
  );

  constructor() {
    // Reload whenever the filter pills or search change. Uses a single
    // source-of-change signal so rapid keypresses coalesce into one
    // request. skip(1) drops toObservable's initial replay so we don't
    // double-fetch — the explicit reload() below owns the first load
    // (it fires immediately without a 300ms debounce delay). The tap
    // flips loading on + clears the stale error banner so filter/search
    // changes always render fresh state.
    const trigger = computed(() => ({
      status: this.statusFilter(),
      search: this.search().trim(),
    }));
    toObservable(trigger)
      .pipe(
        skip(1),
        debounceTime(300),
        distinctUntilChanged((a, b) => a.status === b.status && a.search === b.search),
        tap(() => {
          this.loading.set(true);
          this.loadError.set(null);
        }),
        switchMap(({ status, search }) =>
          this.api.list({
            status: status || undefined,
            search: search || undefined,
            limit: 100,
          }),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.total.set(resp.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load assistants.');
        },
      });
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({
        status: this.statusFilter() || undefined,
        search: this.search().trim() || undefined,
        limit: 100,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.total.set(resp.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load assistants.');
        },
      });
  }

  protected setStatusFilter(v: '' | AiAssistantStatus): void {
    this.statusFilter.set(v);
  }

  protected onSearchInput(event: Event): void {
    this.search.set((event.target as HTMLInputElement).value);
  }

  protected openCreateModal(): void {
    if (!this.canManage()) return;
    this.modalOpen.set(true);
  }

  protected onCreated(row: AiAssistant): void {
    this.modalOpen.set(false);
    // Navigate straight into the editor for the fresh row so the
    // user lands on the config surface they need next. The list
    // rehydrates on back-navigation via the reload() in constructor.
    void this.router.navigate(['/user/ai-assistants', row.id]);
  }

  protected onCreateClosed(): void {
    this.modalOpen.set(false);
  }

  protected toggleKebab(id: string, event: MouseEvent): void {
    event.stopPropagation();
    this.kebabOpenId.update((cur) => (cur === id ? null : id));
  }

  @HostListener('document:keydown.escape')
  protected closeKebab(): void {
    this.kebabOpenId.set(null);
  }

  protected archive(row: AiAssistantListItem): void {
    if (!this.canManage() || this.actionInFlight()) return;
    // Ask before flipping status — archive removes the row from the
    // default filter view and stops the assistant from serving on any
    // bound channel. Confirm dialog is the same one delete uses, minus
    // the danger styling.
    this.kebabOpenId.set(null);
    this.pendingArchive.set(row);
  }

  protected cancelArchive(): void {
    if (this.actionInFlight()) return;
    this.actionError.set(null);
    this.pendingArchive.set(null);
  }

  protected confirmArchive(): void {
    const row = this.pendingArchive();
    if (!row) return;
    this.actionInFlight.set(row.id);
    this.actionError.set(null);
    this.api
      .archive(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.actionInFlight.set(null);
          this.pendingArchive.set(null);
          // Patch the row in place — full grid reload would flash a
          // page-wide skeleton for a single-row status change.
          this.items.update((rows) =>
            rows.map((r) =>
              r.id === row.id ? { ...r, status: 'archived' as AiAssistantStatus } : r,
            ),
          );
          this.toast.success(`“${row.name}” archived`);
        },
        error: (err: HttpErrorResponse) => {
          this.actionInFlight.set(null);
          this.actionError.set(extractApiError(err) ?? 'Archive failed.');
        },
      });
  }

  protected activate(row: AiAssistantListItem): void {
    if (!this.canManage() || this.actionInFlight()) return;
    this.kebabOpenId.set(null);
    this.pendingActivate.set(row);
  }

  protected cancelActivate(): void {
    if (this.actionInFlight()) return;
    this.actionError.set(null);
    this.pendingActivate.set(null);
  }

  protected confirmActivate(): void {
    const row = this.pendingActivate();
    if (!row) return;
    this.actionInFlight.set(row.id);
    this.actionError.set(null);
    this.api
      .activate(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.actionInFlight.set(null);
          this.pendingActivate.set(null);
          this.items.update((rows) =>
            rows.map((r) => (r.id === row.id ? { ...r, status: updated.status } : r)),
          );
          this.toast.success(`“${row.name}” is live`);
        },
        error: (err: HttpErrorResponse) => {
          this.actionInFlight.set(null);
          this.actionError.set(extractApiError(err) ?? 'Activate failed.');
        },
      });
  }

  protected delete(row: AiAssistantListItem): void {
    if (!this.canManage() || this.actionInFlight()) return;
    // Open the styled confirm dialog rather than fire the browser's
    // native ``confirm()`` — the dialog is the same one used across
    // contacts / leads / walk-ins so the destructive-prompt UX stays
    // consistent (and doesn't look like a system alert from the OS).
    this.kebabOpenId.set(null);
    this.pendingDelete.set(row);
  }

  protected cancelDelete(): void {
    if (this.actionInFlight()) return;
    this.actionError.set(null);
    this.pendingDelete.set(null);
  }

  protected confirmDelete(): void {
    const row = this.pendingDelete();
    if (!row) return;
    this.actionInFlight.set(row.id);
    this.actionError.set(null);
    this.api
      .delete(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.actionInFlight.set(null);
          this.pendingDelete.set(null);
          this.items.update((rows) => rows.filter((r) => r.id !== row.id));
          this.total.update((n) => Math.max(0, n - 1));
          this.toast.success(`“${row.name}” deleted`);
        },
        error: (err: HttpErrorResponse) => {
          this.actionInFlight.set(null);
          this.actionError.set(extractApiError(err) ?? 'Delete failed.');
        },
      });
  }

  protected statusBadge(status: AiAssistantStatus) {
    return STATUS_BADGE[status];
  }

  // Small pretty-name + icon helpers for the "which channels does this
  // assistant handle?" pills on each card. Keep in sync with the
  // Deployment checkbox labels in ``instructions-tab.component.ts`` so
  // an operator sees the same wording in both places. ``ai_widget``
  // stays supported for legacy rows but isn't offered as a new binding
  // choice (removed from Deployment in the omnichannel Step 2 tidy-up).
  protected channelLabel(ch: string): string {
    switch (ch) {
      case 'whatsapp':
        return 'WhatsApp';
      case 'email':
        return 'Email';
      case 'ai_widget':
        return 'Website widget';
      default:
        return ch;
    }
  }

  protected channelIcon(ch: string): string {
    switch (ch) {
      case 'whatsapp':
        return 'message-circle';
      case 'email':
        return 'mail';
      case 'ai_widget':
        return 'globe';
      default:
        return 'circle-dot';
    }
  }
}
