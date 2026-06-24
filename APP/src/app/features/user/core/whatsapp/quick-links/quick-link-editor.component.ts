import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { extractApiError } from '@core/services/api-error.util';
import {
  QuickLink,
  QuickLinkUpsert,
  QuickLinksService,
} from './quick-links.service';

/**
 * Editor for a single quick-link (Step 26).
 *
 * Used for both create (`editing=null`) and edit. The prefilled
 * message is the most surprising surface — we warn when it
 * exceeds ~200 chars because WhatsApp's own QR-scan UI starts
 * clipping the preview at that size.
 */
@Component({
  selector: 'app-quick-link-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="space-y-3">
      <header class="flex items-baseline justify-between">
        <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500">
          {{ editing() ? 'Edit link' : 'New quick link' }}
        </p>
        <div class="flex gap-1">
          <button
            type="button"
            (click)="cancel.emit()"
            class="rounded border border-zinc-300 bg-white px-3 py-1.5 text-xs text-zinc-700 hover:bg-zinc-50"
          >
            Cancel
          </button>
          <button
            type="button"
            [disabled]="busy() || !canSave()"
            (click)="save()"
            class="rounded bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-zinc-800 disabled:opacity-50"
          >
            {{ busy() ? 'Saving…' : editing() ? 'Save changes' : 'Create link' }}
          </button>
        </div>
      </header>

      @if (error(); as err) {
        <p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {{ err }}
        </p>
      }

      <label class="block text-xs">
        <span class="mb-1 block font-medium text-zinc-700">Label</span>
        <input
          type="text"
          maxlength="128"
          placeholder="e.g. Mall billboard — Andheri"
          class="w-full rounded-md border border-zinc-300 px-2.5 py-1.5"
          [ngModel]="form().label"
          (ngModelChange)="patch({ label: $event })"
        />
        <span class="mt-1 block text-[11px] text-zinc-500">
          Internal name — never shown to customers.
        </span>
      </label>

      <label class="block text-xs">
        <span class="mb-1 block font-medium text-zinc-700">
          Destination phone (E.164 digits)
        </span>
        <input
          type="tel"
          maxlength="32"
          placeholder="+91 99XXX 88888"
          class="w-full rounded-md border border-zinc-300 px-2.5 py-1.5"
          [ngModel]="form().phone_number"
          (ngModelChange)="patch({ phone_number: $event })"
        />
        <span class="mt-1 block text-[11px] text-zinc-500">
          The WhatsApp number that receives the message.
        </span>
      </label>

      <label class="block text-xs">
        <span class="mb-1 block font-medium text-zinc-700">
          Prefilled message (optional)
        </span>
        <textarea
          rows="3"
          maxlength="2000"
          placeholder="I saw your billboard at Andheri mall — please share the catalogue."
          class="w-full rounded-md border border-zinc-300 px-2.5 py-1.5"
          [ngModel]="form().prefilled_message ?? ''"
          (ngModelChange)="patch({ prefilled_message: $event })"
        ></textarea>
        <span class="mt-1 block text-[11px]" [class.text-amber-700]="warnLength()">
          {{ (form().prefilled_message?.length ?? 0) }} / 200 ideal
          @if (warnLength()) {
            — WhatsApp may truncate the preview on scan.
          }
        </span>
      </label>
    </div>
  `,
})
export class QuickLinkEditorComponent {
  private readonly api = inject(QuickLinksService);
  private readonly destroyRef = inject(DestroyRef);

  readonly editing = input<QuickLink | null>(null);
  readonly saved = output<QuickLink>();
  readonly cancel = output<void>();

  protected readonly form = signal<QuickLinkUpsert>({
    label: '',
    phone_number: '',
    prefilled_message: '',
  });
  protected readonly busy = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);

  constructor() {
    effect(() => {
      const e = this.editing();
      if (e) {
        this.form.set({
          label: e.label,
          phone_number: e.phone_number,
          prefilled_message: e.prefilled_message ?? '',
        });
      } else {
        this.form.set({ label: '', phone_number: '', prefilled_message: '' });
      }
      this.error.set(null);
    });
  }

  protected readonly warnLength = computed(
    () => (this.form().prefilled_message?.length ?? 0) > 200,
  );

  protected canSave(): boolean {
    const f = this.form();
    return Boolean(f.label.trim() && f.phone_number.trim());
  }

  protected patch(patch: Partial<QuickLinkUpsert>): void {
    this.form.update((f) => ({ ...f, ...patch }));
  }

  protected save(): void {
    const f = this.form();
    if (!this.canSave()) return;
    this.busy.set(true);
    this.error.set(null);
    const obs = this.editing()
      ? this.api.update(this.editing()!.id, {
          label: f.label,
          phone_number: f.phone_number,
          prefilled_message: f.prefilled_message ?? null,
        })
      : this.api.create({
          label: f.label,
          phone_number: f.phone_number,
          prefilled_message: f.prefilled_message ?? null,
        });
    obs.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (row) => {
        this.busy.set(false);
        this.saved.emit(row);
      },
      error: (err: HttpErrorResponse) => {
        this.busy.set(false);
        this.error.set(extractApiError(err) ?? 'Could not save link.');
      },
    });
  }
}
