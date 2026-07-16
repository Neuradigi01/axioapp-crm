import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { extractApiError } from '@core/services/api-error.util';
import { purposeBadgeClass } from '@core/services/badge.util';

import {
  FieldOpsApiService,
  FieldVisit,
} from '../../../packs/furniture/field-ops/field-ops-api.service';

/**
 * Staff Dashboard â†’ Field Operations tab. Replaces the Step-3.5
 * placeholder with a compact org-wide visit roll-up.
 */
@Component({
  selector: 'app-staff-field-ops-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
  templateUrl: './field-ops.component.html',
})
export class StaffFieldOpsTabComponent {
  protected readonly purposeBadgeClass = purposeBadgeClass;
  private readonly api = inject(FieldOpsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly visits = signal<FieldVisit[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly counts = computed(() => {
    const open = this.visits().filter((v) => !v.completed_at).length;
    const done = this.visits().filter((v) => v.completed_at).length;
    return { open, done, total: this.visits().length };
  });

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({ size: 50 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.visits.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.visits.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load field visits.');
        },
      });
  }

  protected formatRelative(iso: string | null): string {
    if (!iso) return 'â€”';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'short',
    });
  }
}
