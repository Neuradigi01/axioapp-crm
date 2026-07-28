import { CommonModule, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import {
  AutomationRunStatus,
  AutomationsApiService,
  RunRead,
} from '../../automations/automations-api.service';

/**
 * Automations tab on the contact detail page.
 *
 * Lists every automation run that targeted this contact, newest
 * first. Each row: trigger name link (→ /user/automations/:id),
 * channel chip, status badge, scheduled time, error (when
 * failed). Step 14 will add open / click metrics; v1 surfaces the
 * status alone.
 *
 * Read-only — gated on `automations.runs.read` server-side (the
 * tab still renders the empty state for users without the perm
 * because the contact detail page's tab list isn't permission-
 * filtered today).
 */

const STATUS_PALETTE: Record<AutomationRunStatus, string> = {
  queued: 'bg-surface-2 text-default border-subtle',
  dispatched: 'bg-blue-50 text-blue-700 ring-blue-200',
  sent: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  failed: 'bg-red-500/10 text-red-400 ring-red-500/20',
  skipped: 'bg-amber-50 text-amber-700 ring-amber-200',
};

@Component({
  selector: 'app-contact-automations-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink, DatePipe, LucideAngularModule],
  templateUrl: './automations-tab.component.html',
})
export class ContactAutomationsTabComponent {
  private readonly api = inject(AutomationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly contactId = input.required<string>();

  protected readonly STATUS_PALETTE = STATUS_PALETTE;

  protected readonly items = signal<RunRead[]>([]);
  protected readonly total = signal<number>(0);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);

  constructor() {
    effect(() => {
      const id = this.contactId();
      if (id) this.reload(id);
    });
  }

  private reload(contactId: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .listRunsByFilters({ contact_id: contactId, limit: 50 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.items.set(res.items);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.total.set(0);
          this.loading.set(false);
          // 403 (no automations.runs.read) is fine — surface a
          // muted empty state rather than an error.
          if (err.status !== 403) {
            this.loadError.set('Could not load automation runs.');
          }
        },
      });
  }

  protected trackById = (_: number, row: RunRead) => row.id;
}
