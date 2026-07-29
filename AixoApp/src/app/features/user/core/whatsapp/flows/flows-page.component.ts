import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FlowBuilderComponent } from './flow-builder.component';
import { FlowTemplatePickerComponent } from './flow-template-picker.component';
import { FlowCategory, FlowRow, FlowsService } from './flows.service';

type Mode = 'list' | 'pick' | 'build';

/**
 * Step 25 — `/user/whatsapp/flows` library page.
 *
 * Three modes:
 *   * `list`  — table of flows with publish / test-send / archive.
 *   * `pick`  — template picker (4 cards).
 *   * `build` — `FlowBuilderComponent`, seeded with the picked
 *               template OR an existing row for edit.
 */
@Component({
  selector: 'app-whatsapp-flows-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    LucideAngularModule,
    FlowTemplatePickerComponent,
    FlowBuilderComponent,
  ],
  template: `
    <div class="space-y-4 p-4">
      <header class="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 class="text-xl font-semibold text-default">WhatsApp Flows</h1>
          <p class="text-xs text-muted">
            In-chat forms (booking, lead capture, feedback) customers fill inside WhatsApp.
          </p>
        </div>
        @if (mode() === 'list') {
          <button
            type="button"
            (click)="openPicker()"
            class="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:brightness-95"
          >
            <lucide-icon name="plus" class="h-3.5 w-3.5" />
            New flow
          </button>
        } @else {
          <button
            type="button"
            (click)="backToList()"
            class="inline-flex items-center gap-1.5 rounded-md border border-subtle bg-surface px-3 py-1.5 text-xs text-default hover:bg-surface-2"
          >
            <lucide-icon name="arrow-left" class="h-3.5 w-3.5" />
            Back
          </button>
        }
      </header>

      @if (error(); as err) {
        <p class="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400">
          {{ err }}
        </p>
      }
      @if (toast(); as msg) {
        <p class="rounded-md border border-subtle bg-surface-2 px-3 py-2 text-xs text-default">
          {{ msg }}
        </p>
      }

      @switch (mode()) {
        @case ('list') {
          @if (loading()) {
            <p class="text-[11px] text-muted">Loading…</p>
          }
          <div class="overflow-hidden rounded-md border border-subtle bg-surface">
            <table class="w-full text-xs">
              <thead class="bg-surface-2 text-muted">
                <tr>
                  <th class="px-3 py-2 text-left font-medium">Name</th>
                  <th class="px-3 py-2 text-left font-medium">Category</th>
                  <th class="px-3 py-2 text-left font-medium">Status</th>
                  <th class="px-3 py-2 text-left font-medium">Updated</th>
                  <th class="px-3 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-subtle">
                @for (row of flows(); track row.id) {
                  <tr>
                    <td class="px-3 py-2 font-medium text-default">
                      {{ row.name }}
                    </td>
                    <td class="px-3 py-2">
                      <span
                        [class]="
                          'inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ' +
                          categoryClasses(row.category)
                        "
                      >
                        {{ humanCategory(row.category) }}
                      </span>
                    </td>
                    <td class="px-3 py-2">
                      <span
                        [class]="
                          'inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ' +
                          statusClasses(row.status)
                        "
                      >
                        {{ row.status }}
                      </span>
                    </td>
                    <td class="px-3 py-2 text-muted">
                      {{ formatDate(row.updated_at) }}
                    </td>
                    <td class="px-3 py-2 text-right">
                      <div class="inline-flex items-center gap-1">
                        <button
                          type="button"
                          (click)="onEdit(row)"
                          class="rounded border border-subtle bg-surface px-2 py-1 text-[11px] text-default hover:bg-surface-2"
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          [disabled]="busyId() === row.id"
                          (click)="onPublish(row)"
                          class="rounded bg-emerald-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                        >
                          {{ row.status === 'published' ? 'Re-publish' : 'Publish' }}
                        </button>
                        @if (row.status === 'published') {
                          <button
                            type="button"
                            (click)="onTestSend(row)"
                            class="rounded border border-subtle bg-surface px-2 py-1 text-[11px] text-default hover:bg-surface-2"
                          >
                            Test send
                          </button>
                        }
                        <button
                          type="button"
                          (click)="onArchive(row)"
                          class="rounded border border-red-500/30 bg-surface px-2 py-1 text-[11px] text-red-400 hover:bg-red-500/10"
                        >
                          Archive
                        </button>
                      </div>
                    </td>
                  </tr>
                } @empty {
                  <tr>
                    <td colspan="5" class="px-3 py-6 text-center text-muted">
                      No flows yet. Click <em>New flow</em> to start from a template.
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
        @case ('pick') {
          <app-flow-template-picker (pick)="onTemplatePicked($event)" />
        }
        @case ('build') {
          @if (templateSeed(); as seed) {
            <app-flow-builder
              [existing]="editing()"
              [seedTemplate]="seed"
              (saved)="onSaved($event)"
              (cancel)="backToList()"
            />
          } @else {
            <app-flow-builder
              [existing]="editing()"
              (saved)="onSaved($event)"
              (cancel)="backToList()"
            />
          }
        }
      }
    </div>
  `,
})
export class WhatsAppFlowsPageComponent {
  private readonly api = inject(FlowsService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly mode = signal<Mode>('list');
  protected readonly flows = signal<FlowRow[]>([]);
  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);
  protected readonly busyId = signal<string | null>(null);

  protected readonly editing = signal<FlowRow | null>(null);
  protected readonly templateSeed = signal<{
    category: FlowCategory;
    definition: Record<string, unknown>;
  } | null>(null);

  constructor() {
    this.load();
  }

  protected backToList(): void {
    this.mode.set('list');
    this.editing.set(null);
    this.templateSeed.set(null);
    this.error.set(null);
    this.toast.set(null);
  }

  protected openPicker(): void {
    this.mode.set('pick');
    this.editing.set(null);
    this.templateSeed.set(null);
    this.error.set(null);
    this.toast.set(null);
  }

  protected onTemplatePicked(category: FlowCategory): void {
    // The picker only returns the category; the builder fetches a
    // fresh draft definition by creating a placeholder via the API
    // on first save. We seed locally so the operator sees the
    // bundled template fields immediately.
    this.api
      .create({
        name: `Untitled ${category}`,
        category,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.editing.set(row);
          this.templateSeed.set({
            category: row.category,
            definition: row.json_definition,
          });
          this.mode.set('build');
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Could not create flow.');
        },
      });
  }

  protected onEdit(row: FlowRow): void {
    this.editing.set(row);
    this.templateSeed.set({
      category: row.category,
      definition: row.json_definition,
    });
    this.mode.set('build');
  }

  protected onSaved(row: FlowRow): void {
    this.toast.set(`Saved "${row.name}".`);
    this.editing.set(row);
    this.load();
  }

  protected onPublish(row: FlowRow): void {
    this.busyId.set(row.id);
    this.error.set(null);
    this.api
      .publish(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busyId.set(null);
          this.toast.set(`Published "${row.name}".`);
          this.load();
        },
        error: (err: HttpErrorResponse) => {
          this.busyId.set(null);
          this.error.set(extractApiError(err) ?? 'Publish failed.');
        },
      });
  }

  protected onTestSend(row: FlowRow): void {
    const to = prompt(`Send "${row.name}" to which phone number?\n(E.164 format, e.g. +91…)`);
    if (!to) return;
    this.api
      .testSend(row.id, to)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.toast.set(`Test send queued to ${to}.`),
        error: (err: HttpErrorResponse) =>
          this.error.set(extractApiError(err) ?? 'Test send failed.'),
      });
  }

  protected onArchive(row: FlowRow): void {
    if (!confirm(`Archive "${row.name}"? Customers can't open it after this.`)) {
      return;
    }
    this.api
      .remove(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.toast.set(`Archived "${row.name}".`);
          this.load();
        },
        error: (err: HttpErrorResponse) =>
          this.error.set(extractApiError(err) ?? 'Archive failed.'),
      });
  }

  protected humanCategory(c: string): string {
    switch (c) {
      case 'appointment_booking':
        return 'Appointment';
      case 'lead_capture':
        return 'Lead capture';
      case 'feedback':
        return 'Feedback';
      case 'signup':
        return 'Sign-up';
      default:
        return 'Custom';
    }
  }

  protected categoryClasses(c: string): string {
    switch (c) {
      case 'appointment_booking':
        return 'bg-blue-50 text-blue-700 ring-blue-200';
      case 'lead_capture':
        return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
      case 'feedback':
        return 'bg-amber-50 text-amber-700 ring-amber-200';
      case 'signup':
        return 'bg-violet-50 text-violet-700 ring-violet-200';
      default:
        return 'bg-surface-2 text-muted border-subtle';
    }
  }

  protected statusClasses(s: string): string {
    switch (s) {
      case 'published':
        return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
      case 'archived':
        return 'bg-surface-2 text-muted border-subtle';
      default:
        return 'bg-amber-50 text-amber-700 ring-amber-200';
    }
  }

  protected formatDate(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  private load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (list) => {
          this.flows.set(list);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load flows.');
        },
      });
  }
}
