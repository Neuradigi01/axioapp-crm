/**
 * Settings → Integrations → AI Providers → Reassign modal
 * (``tasks/ai-assistants`` Step 3).
 *
 * Opens when the operator tries to DELETE a key that N assistants
 * reference. Lets them pick a target key from the same org's list,
 * then chains ``POST /reassign`` → ``DELETE /providers/{id}``.
 *
 * v1 note: the actual bulk-UPDATE landing on the assistants table
 * is Step 5. Until then, the reassign endpoint returns 501 with a
 * pointer message — the operator sees a friendly "reassign not yet
 * available" prompt. The Delete flow still surfaces the count so
 * they can plan for the eventual removal.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { AiProviderKey, AiProvidersApiService } from './ai-providers-api.service';

@Component({
  selector: 'app-ai-providers-reassign-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule],
  templateUrl: './ai-providers-reassign-modal.component.html',
})
export class AiProvidersReassignModalComponent {
  private readonly api = inject(AiProvidersApiService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  /** The key the operator tried to delete. */
  readonly fromKey = input.required<AiProviderKey>();
  /** How many assistants reference the key. */
  readonly referenceCount = input.required<number>();
  /** Every other key the caller could reassign to. */
  readonly candidates = input.required<AiProviderKey[]>();

  readonly reassigned = output<void>();
  readonly closed = output<void>();

  protected readonly form = this.fb.nonNullable.group({
    to_key_id: this.fb.nonNullable.control<string>('', { validators: [Validators.required] }),
  });

  protected readonly saving = signal(false);
  protected readonly saveError = signal<string | null>(null);
  protected readonly notYetAvailable = signal(false);

  protected readonly canSave = computed(
    () => this.form.valid && !this.saving() && !this.notYetAvailable(),
  );

  protected close(): void {
    if (this.saving()) return;
    this.closed.emit();
  }

  protected reassignAndDelete(): void {
    if (!this.canSave()) return;
    const { to_key_id } = this.form.getRawValue();
    if (!to_key_id) return;
    this.saving.set(true);
    this.saveError.set(null);
    this.notYetAvailable.set(false);

    this.api
      .reassign({ from_key_id: this.fromKey().id, to_key_id })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          // Chain into DELETE now that references are cleared.
          this.api
            .delete(this.fromKey().id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
              next: () => {
                this.saving.set(false);
                this.reassigned.emit();
              },
              error: (err: HttpErrorResponse) => {
                this.saving.set(false);
                this.saveError.set(extractApiError(err) ?? 'Delete failed after reassign.');
              },
            });
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          // Step 1 stubs reassign until Step 5 lands. Surface a
          // friendly message so the operator understands why the
          // button appears but does nothing yet.
          if (err.status === 501) {
            this.notYetAvailable.set(true);
          } else {
            this.saveError.set(extractApiError(err) ?? 'Reassign failed.');
          }
        },
      });
  }
}
