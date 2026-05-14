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

import {
  FieldOpsApiService,
  FieldVisit,
} from '../../../packs/furniture/field-ops/field-ops-api.service';

/**
 * Staff Dashboard → Field Operations tab. Replaces the Step-3.5
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
          this.loadError.set(
            this.extractError(err) ?? 'Could not load field visits.',
          );
        },
      });
  }

  protected formatRelative(iso: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'short',
    });
  }

  protected purposeBadgeClass(purpose: string): string {
    switch (purpose) {
      case 'measurement':
        return 'bg-sky-100 text-sky-700 ring-sky-200';
      case 'installation':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      case 'inspection':
        return 'bg-violet-100 text-violet-700 ring-violet-200';
      default:
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
    }
  }

  private extractError(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}
