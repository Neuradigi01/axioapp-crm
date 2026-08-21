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
  computed,
  inject,
  signal,
} from '@angular/core';
import { toObservable } from '@angular/core/rxjs-interop';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';
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
  protected readonly actionInFlight = signal<string | null>(null);

  protected readonly statusPills = STATUS_PILLS;

  protected readonly canManage = computed(() =>
    this.auth.currentPermissions().includes('ai_assistants.manage'),
  );

  protected readonly emptyState = computed(
    () =>
      !this.loading() && this.items().length === 0 && this.statusFilter() === '' && !this.search(),
  );

  constructor() {
    // Reload whenever the filter pills or search change (debounced
    // for search only). Uses a single source-of-change signal so
    // rapid keypresses coalesce into one request.
    const trigger = computed(() => ({
      status: this.statusFilter(),
      search: this.search().trim(),
    }));
    toObservable(trigger)
      .pipe(
        debounceTime(300),
        distinctUntilChanged((a, b) => a.status === b.status && a.search === b.search),
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
    // Kick off the first fetch — toObservable doesn't emit for the
    // initial signal value on its own with this pipe shape.
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

  protected closeKebab(): void {
    this.kebabOpenId.set(null);
  }

  protected archive(row: AiAssistantListItem): void {
    if (!this.canManage() || this.actionInFlight()) return;
    this.actionInFlight.set(row.id);
    this.kebabOpenId.set(null);
    this.api
      .archive(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.actionInFlight.set(null);
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.actionInFlight.set(null);
          this.loadError.set(extractApiError(err) ?? 'Archive failed.');
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
    this.pendingDelete.set(null);
  }

  protected confirmDelete(): void {
    const row = this.pendingDelete();
    if (!row) return;
    this.actionInFlight.set(row.id);
    this.loadError.set(null);
    this.api
      .delete(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.actionInFlight.set(null);
          this.pendingDelete.set(null);
          this.items.update((rows) => rows.filter((r) => r.id !== row.id));
          this.total.update((n) => Math.max(0, n - 1));
        },
        error: (err: HttpErrorResponse) => {
          this.actionInFlight.set(null);
          this.loadError.set(extractApiError(err) ?? 'Delete failed.');
          this.pendingDelete.set(null);
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
        return 'circle';
    }
  }
}
