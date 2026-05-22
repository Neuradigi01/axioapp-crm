import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import {
  ImportsApiService,
  LeadImport,
} from './imports-api.service';

/**
 * Placeholder for `/user/leads/import/:id/mapping` until Step 5 of the
 * bulk-import track builds the real column-mapping UI.
 *
 * Step 4's upload-page navigates here on a successful upload, so we
 * need *something* to render — a totally absent route would surface
 * as a 404 + break the smoke for Step 4. This shows the import row's
 * current state (status / row count / source platform) and a "Back
 * to leads" link. Delete this file in Step 5 and swap the route to
 * the real `MappingPageComponent`.
 */
@Component({
  selector: 'app-import-mapping-placeholder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
  template: `
    <div class="mx-auto max-w-3xl p-6 space-y-5">
      <header class="space-y-1">
        <nav class="flex items-center gap-1 text-xs text-zinc-500">
          <a routerLink="/user/leads" class="hover:text-zinc-700">Leads</a>
          <lucide-icon name="chevron-right" class="h-3 w-3" />
          <a routerLink="/user/leads/import" class="hover:text-zinc-700">Import</a>
          <lucide-icon name="chevron-right" class="h-3 w-3" />
          <span class="text-zinc-700">Mapping</span>
        </nav>
        <h1 class="text-lg font-semibold text-zinc-900">Map columns</h1>
      </header>

      @if (loading()) {
        <p class="text-sm text-zinc-500">Loading import…</p>
      } @else if (error(); as msg) {
        <p class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {{ msg }}
        </p>
      } @else if (importRow(); as row) {
        <div class="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          The column-mapping UI ships in Step 5 of the bulk-import track.
          For now you can confirm the upload landed below.
        </div>
        <dl class="grid grid-cols-2 gap-3 rounded-md border border-zinc-200 bg-white p-4 text-sm">
          <dt class="text-zinc-500">Name</dt>
          <dd class="font-medium text-zinc-900">{{ row.name }}</dd>
          <dt class="text-zinc-500">Source platform</dt>
          <dd class="text-zinc-900">{{ row.source_platform }}</dd>
          <dt class="text-zinc-500">File</dt>
          <dd class="truncate text-zinc-900">{{ row.original_filename }}</dd>
          <dt class="text-zinc-500">Row count (est.)</dt>
          <dd class="text-zinc-900">{{ row.row_count_estimate }}</dd>
          <dt class="text-zinc-500">Status</dt>
          <dd class="text-zinc-900">{{ row.status }}</dd>
        </dl>
        <div class="text-right">
          <a routerLink="/user/leads" class="text-sm text-indigo-600 hover:text-indigo-700">
            ← Back to leads
          </a>
        </div>
      }
    </div>
  `,
})
export class MappingPagePlaceholderComponent {
  private readonly api = inject(ImportsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly importRow = signal<LeadImport | null>(null);

  constructor() {
    const importId = this.route.snapshot.paramMap.get('id');
    if (!importId) {
      this.loading.set(false);
      this.error.set('No import id in the route.');
      return;
    }
    this.api
      .get(importId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.importRow.set(row);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
          this.error.set('Could not load this import.');
        },
      });
  }
}
