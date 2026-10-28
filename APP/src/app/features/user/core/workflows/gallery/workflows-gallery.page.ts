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
import { Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { WorkflowGalleryEntry, WorkflowsApiService } from '../workflows-api.service';
import { CloneNameModalComponent } from './clone-name.modal.component';
import { GalleryPreviewModalComponent } from './preview.modal.component';

/**
 * Workflow templates gallery — Step 16's first frontend surface.
 *
 * URL: `/user/workflows/gallery`. Loads the 15-entry catalogue from
 * `GET /workflows/gallery`, renders a card grid with a category-tab
 * filter at the top. Each card opens a read-only preview modal; the
 * "Use this template" CTA launches the naming modal which posts to
 * the clone endpoint and routes the operator into the canvas editor
 * for the new draft.
 *
 * Layout follows HubSpot's template-gallery pattern: clean cards with
 * channel chips + estimated setup time + completion rate.
 */

const ALL_TAB = '__all__';

@Component({
  selector: 'app-workflows-gallery',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    LucideAngularModule,
    GalleryPreviewModalComponent,
    CloneNameModalComponent,
  ],
  templateUrl: './workflows-gallery.page.html',
})
export class WorkflowsGalleryPageComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly entries = signal<WorkflowGalleryEntry[]>([]);
  readonly activeCategory = signal<string>(ALL_TAB);

  readonly previewEntry = signal<WorkflowGalleryEntry | null>(null);
  readonly cloneEntry = signal<WorkflowGalleryEntry | null>(null);
  readonly cloneBusy = signal(false);

  readonly ALL_TAB = ALL_TAB;

  readonly categories = computed<string[]>(() => {
    const seen = new Set<string>();
    for (const e of this.entries()) {
      seen.add(e.category);
    }
    return Array.from(seen);
  });

  readonly filteredEntries = computed<WorkflowGalleryEntry[]>(() => {
    const cat = this.activeCategory();
    if (cat === ALL_TAB) return this.entries();
    return this.entries().filter((e) => e.category === cat);
  });

  constructor() {
    this.loadGallery();
  }

  private loadGallery(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .listGallery()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.entries.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Could not load the templates gallery.');
          this.loading.set(false);
        },
      });
  }

  setCategory(category: string): void {
    this.activeCategory.set(category);
  }

  openPreview(entry: WorkflowGalleryEntry): void {
    this.previewEntry.set(entry);
  }

  closePreview(): void {
    this.previewEntry.set(null);
  }

  startClone(entry: WorkflowGalleryEntry): void {
    // Allow launching the clone modal from the card OR from inside
    // the preview modal — closing the preview first keeps focus
    // management sane.
    this.previewEntry.set(null);
    this.cloneEntry.set(entry);
  }

  cancelClone(): void {
    if (this.cloneBusy()) return;
    this.cloneEntry.set(null);
  }

  confirmClone(payload: { name: string }): void {
    const entry = this.cloneEntry();
    if (!entry) return;
    this.cloneBusy.set(true);
    this.error.set(null);
    this.api
      .cloneFromGallery(entry.id, { name: payload.name })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (workflow) => {
          this.cloneBusy.set(false);
          this.cloneEntry.set(null);
          this.router.navigate(['/user/workflows', workflow.id]);
        },
        error: (err: HttpErrorResponse) => {
          this.cloneBusy.set(false);
          this.error.set(extractApiError(err) ?? 'Clone failed.');
        },
      });
  }
}
