import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';

import {
  WhatsAppTemplateRead,
  WhatsAppTemplateSubmissionStatus,
  WhatsAppTemplateUpsert,
  WhatsAppTemplatesApiService,
} from './whatsapp-templates-api.service';
import { TemplatePerformanceComponent } from './template-performance.component';
import { TemplateWizardComponent } from './template-wizard.component';

/**
 * Templates page — list + wizard host
 * (whatsapp-platform-upgrade Step 9).
 *
 * Single-route owner for the entire surface. The wizard is mounted
 * inline (not a route) so a Cancel click returns the user to the list
 * with zero navigation cost. Permissions:
 *
 *   - LIST view: `whatsapp.templates.read` (route guard)
 *   - Create / Edit / Duplicate / Delete: `whatsapp.templates.write`
 *   - Submit to Meta: `whatsapp.templates.submit`
 */

type WizardMode = 'create' | 'edit' | null;

const STATUS_BADGE: Record<
  WhatsAppTemplateSubmissionStatus,
  { label: string; classes: string }
> = {
  draft: {
    label: 'Draft',
    classes: 'bg-zinc-100 text-zinc-700 ring-zinc-200',
  },
  pending_review: {
    label: 'Pending',
    classes: 'bg-amber-50 text-amber-700 ring-amber-200',
  },
  approved: {
    label: 'Approved',
    classes: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  },
  rejected: {
    label: 'Rejected',
    classes: 'bg-rose-50 text-rose-700 ring-rose-200',
  },
  paused: {
    label: 'Paused',
    classes: 'bg-orange-50 text-orange-700 ring-orange-200',
  },
  disabled: {
    label: 'Disabled',
    classes: 'bg-zinc-100 text-zinc-500 ring-zinc-300',
  },
};

const FILTER_TABS: Array<{
  key: WhatsAppTemplateSubmissionStatus | 'all';
  label: string;
}> = [
  { key: 'all', label: 'All' },
  { key: 'draft', label: 'Drafts' },
  { key: 'pending_review', label: 'Pending' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Rejected' },
];


@Component({
  selector: 'app-whatsapp-templates-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    LucideAngularModule,
    TemplatePerformanceComponent,
    TemplateWizardComponent,
  ],
  templateUrl: './whatsapp-templates.page.html',
})
export class WhatsAppTemplatesPageComponent {
  private readonly api = inject(WhatsAppTemplatesApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly STATUS_BADGE = STATUS_BADGE;
  protected readonly FILTER_TABS = FILTER_TABS;

  protected readonly items = signal<WhatsAppTemplateRead[]>([]);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);

  protected readonly activeFilter =
    signal<WhatsAppTemplateSubmissionStatus | 'all'>('all');
  protected readonly searchQuery = signal<string>('');

  protected readonly wizardMode = signal<WizardMode>(null);
  protected readonly editingTemplate = signal<WhatsAppTemplateRead | null>(null);
  protected readonly wizardSubmitting = signal<boolean>(false);
  protected readonly wizardError = signal<string | null>(null);

  /** Step 10: when set, render the per-template performance card
   *  instead of the list / wizard. Click "Back to list" clears it. */
  protected readonly viewingPerformance =
    signal<WhatsAppTemplateRead | null>(null);

  /** Per-row spinner state for submit / duplicate / delete. */
  protected readonly busyRowId = signal<string | null>(null);

  protected readonly canWrite = computed(() =>
    this.auth.hasPermission('whatsapp.templates.write'),
  );
  protected readonly canSubmit = computed(() =>
    this.auth.hasPermission('whatsapp.templates.submit'),
  );

  protected readonly filteredItems = computed(() => {
    const filter = this.activeFilter();
    const q = this.searchQuery().trim().toLowerCase();
    return this.items().filter((row) => {
      if (filter !== 'all' && row.submission_status !== filter) return false;
      if (q && !row.name.toLowerCase().includes(q)) return false;
      return true;
    });
  });

  constructor() {
    this.reload();
  }

  // --- list -------------------------------------------------------

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.items.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load templates.',
          );
        },
      });
  }

  protected setFilter(
    filter: WhatsAppTemplateSubmissionStatus | 'all',
  ): void {
    this.activeFilter.set(filter);
  }

  protected onSearchChange(value: string): void {
    this.searchQuery.set(value);
  }

  protected dismissToast(): void {
    this.toast.set(null);
  }

  // --- wizard -----------------------------------------------------

  protected openCreate(): void {
    if (!this.canWrite()) return;
    this.editingTemplate.set(null);
    this.wizardError.set(null);
    this.wizardMode.set('create');
  }

  protected openPerformance(row: WhatsAppTemplateRead): void {
    this.viewingPerformance.set(row);
  }

  protected closePerformance(): void {
    this.viewingPerformance.set(null);
  }

  protected openEdit(row: WhatsAppTemplateRead): void {
    if (!this.canWrite()) return;
    if (row.submission_status !== 'draft' && row.submission_status !== 'rejected') {
      this.toast.set(
        'Approved and pending templates can\'t be edited. Use Duplicate to clone instead.',
      );
      return;
    }
    this.editingTemplate.set(row);
    this.wizardError.set(null);
    this.wizardMode.set('edit');
  }

  protected closeWizard(): void {
    this.wizardMode.set(null);
    this.editingTemplate.set(null);
    this.wizardSubmitting.set(false);
    this.wizardError.set(null);
  }

  protected onWizardSubmit(payload: WhatsAppTemplateUpsert): void {
    this.wizardSubmitting.set(true);
    this.wizardError.set(null);
    const editing = this.editingTemplate();
    const request$ = editing
      ? this.api.update(editing.id, payload)
      : this.api.create(payload);
    request$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.wizardSubmitting.set(false);
          this.upsertRow(row);
          this.toast.set(
            editing
              ? 'Template saved.'
              : 'Draft saved. Submit it to send to Meta for approval.',
          );
          this.closeWizard();
        },
        error: (err: HttpErrorResponse) => {
          this.wizardSubmitting.set(false);
          this.wizardError.set(
            extractApiError(err) ?? 'Could not save the template.',
          );
        },
      });
  }

  // --- row actions ------------------------------------------------

  protected submitToMeta(row: WhatsAppTemplateRead): void {
    if (!this.canSubmit()) return;
    this.busyRowId.set(row.id);
    this.api
      .submit(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.busyRowId.set(null);
          this.items.update((rows) =>
            rows.map((r) =>
              r.id === row.id
                ? {
                    ...r,
                    submission_status: res.submission_status,
                    meta_template_id: res.meta_template_id,
                    status: res.meta_status ?? r.status,
                  }
                : r,
            ),
          );
          this.toast.set(
            'Template submitted — Meta review usually takes 30 min to 24 hr.',
          );
        },
        error: (err: HttpErrorResponse) => {
          this.busyRowId.set(null);
          this.toast.set(
            extractApiError(err) ?? 'Could not submit the template.',
          );
        },
      });
  }

  protected duplicate(row: WhatsAppTemplateRead): void {
    if (!this.canWrite()) return;
    this.busyRowId.set(row.id);
    this.api
      .duplicate(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (newRow) => {
          this.busyRowId.set(null);
          this.items.update((rows) => [newRow, ...rows]);
          this.toast.set(`Duplicate created: "${newRow.name}"`);
        },
        error: (err: HttpErrorResponse) => {
          this.busyRowId.set(null);
          this.toast.set(
            extractApiError(err) ?? 'Could not duplicate the template.',
          );
        },
      });
  }

  protected confirmDelete(row: WhatsAppTemplateRead): void {
    if (!this.canWrite()) return;
    const message =
      row.meta_template_id
        ? `Delete template "${row.name}"? It will also be removed from Meta.`
        : `Delete draft "${row.name}"?`;
    if (!confirm(message)) return;
    this.busyRowId.set(row.id);
    this.api
      .delete(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busyRowId.set(null);
          this.items.update((rows) => rows.filter((r) => r.id !== row.id));
          this.toast.set('Template deleted.');
        },
        error: (err: HttpErrorResponse) => {
          this.busyRowId.set(null);
          this.toast.set(
            extractApiError(err) ?? 'Could not delete the template.',
          );
        },
      });
  }

  private upsertRow(row: WhatsAppTemplateRead): void {
    this.items.update((rows) => {
      const idx = rows.findIndex((r) => r.id === row.id);
      if (idx === -1) return [row, ...rows];
      const next = rows.slice();
      next[idx] = row;
      return next;
    });
  }
}
