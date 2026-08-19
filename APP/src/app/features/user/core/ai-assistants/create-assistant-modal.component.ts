/**
 * Create Assistant modal (``tasks/ai-assistants`` Step 7).
 *
 * Minimal two-field flow: pick a stored OpenAI provider key + type
 * a name. POST creates a draft assistant with sensible defaults
 * (model = ``gpt-4o-mini``, temperature = 0.5); the caller then
 * routes into the editor for the fresh row.
 *
 * If the org has no provider keys stored yet, the select shows an
 * inline "Configure a key in Settings → Integrations" link — no
 * assistant can exist without a key (backend FK is RESTRICT).
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  output,
  signal,
} from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { AiProviderKey } from '../settings/integrations/ai-providers-api.service';
import { AiAssistant, AiAssistantsApiService } from './ai-assistants-api.service';

@Component({
  selector: 'app-create-assistant-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule],
  templateUrl: './create-assistant-modal.component.html',
})
export class CreateAssistantModalComponent {
  private readonly api = inject(AiAssistantsApiService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  /** Emitted after the POST returns 201. Parent navigates into the
   *  editor with the created row's id. */
  readonly created = output<AiAssistant>();
  /** Emitted on Cancel or backdrop click. */
  readonly closed = output<void>();

  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);
  protected readonly keys = signal<AiProviderKey[]>([]);
  protected readonly saving = signal(false);
  protected readonly saveError = signal<string | null>(null);

  protected readonly form = this.fb.nonNullable.group({
    name: this.fb.nonNullable.control<string>('', {
      validators: [Validators.required, Validators.minLength(1), Validators.maxLength(200)],
    }),
    key_id: this.fb.nonNullable.control<string>('', {
      validators: [Validators.required],
    }),
  });

  protected readonly hasKeys = computed(() => this.keys().length > 0);
  protected readonly canSave = computed(() => this.form.valid && !this.saving() && this.hasKeys());

  constructor() {
    // Load provider keys — filter to non-revoked so the user can't
    // pick a key that will fail at chat time.
    this.api
      .listProviderKeys()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          const live = rows.filter((r) => !r.revoked_at);
          this.keys.set(live);
          if (live.length > 0) {
            this.form.patchValue({ key_id: live[0].id });
          }
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load provider keys.');
        },
      });
  }

  protected close(): void {
    if (this.saving()) return;
    this.closed.emit();
  }

  protected save(): void {
    if (!this.canSave()) return;
    this.saving.set(true);
    this.saveError.set(null);
    const raw = this.form.getRawValue();
    this.api
      .create({
        name: raw.name.trim(),
        key_id: raw.key_id,
        model: 'gpt-4o-mini',
        temperature: 0.5,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.saving.set(false);
          this.created.emit(row);
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.saveError.set(extractApiError(err) ?? 'Create failed.');
        },
      });
  }
}
