import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  inject,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { extractApiError } from '@core/services/api-error.util';
import { FlowCategory, FlowTemplate, FlowsService } from './flows.service';

/**
 * Step 25 — template picker (4 cards: appointment / lead /
 * feedback / blank custom). Emits ``(pick)`` with the operator's
 * choice; the parent page swaps to the builder with the bundled
 * JSON pre-loaded.
 */
@Component({
  selector: 'app-flow-template-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    <div class="space-y-3">
      <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Pick a template to start from
      </p>
      @if (loading()) {
        <p class="text-[11px] text-zinc-500">Loading templates…</p>
      }
      @if (error(); as err) {
        <p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {{ err }}
        </p>
      }
      <div class="grid grid-cols-1 gap-2 md:grid-cols-2">
        @for (t of templates(); track t.key) {
          <button
            type="button"
            (click)="onPick(t.key)"
            class="flex flex-col items-start gap-1 rounded-md border border-zinc-200 bg-white px-3 py-3 text-left transition hover:border-zinc-400 hover:bg-zinc-50"
          >
            <span class="text-sm font-semibold text-zinc-900">
              {{ t.label }}
            </span>
            <span class="text-[11px] text-zinc-500">
              {{ t.description }}
            </span>
          </button>
        }
      </div>
    </div>
  `,
})
export class FlowTemplatePickerComponent implements OnInit {
  private readonly api = inject(FlowsService);
  private readonly destroyRef = inject(DestroyRef);

  readonly pick = output<FlowCategory>();

  protected readonly templates = signal<FlowTemplate[]>([]);
  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);

  ngOnInit(): void {
    this.loading.set(true);
    this.api
      .listTemplates()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (list) => {
          this.templates.set(list);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load templates.');
        },
      });
  }

  protected onPick(key: FlowCategory): void {
    this.pick.emit(key);
  }
}
