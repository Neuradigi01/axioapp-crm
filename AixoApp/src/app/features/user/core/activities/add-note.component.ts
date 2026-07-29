import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { commonValidators } from '../shared/validators';
import { Activity, ActivitiesApiService } from './activities-api.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Lightweight composer for a manual note on any tenant-scoped entity.
 *
 * Emits `created` after the server confirms persistence; the parent is
 * expected to prepend the row to the timeline (or call its `reload()`)
 * so the new note is visible immediately. The textarea clears itself
 * on success.
 *
 * Reusable: same component will back the note composer for Leads and
 * Walk-ins later — no entity-type knowledge lives here.
 */
@Component({
  selector: 'app-add-note',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './add-note.component.html',
})
export class AddNoteComponent {
  private readonly api = inject(ActivitiesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly entityType = input.required<string>();
  readonly entityId = input.required<string>();

  readonly created = output<Activity>();

  readonly text = new FormControl('', {
    nonNullable: true,
    validators: [
      commonValidators.trimmedRequired,
      Validators.minLength(2),
      Validators.maxLength(4000),
    ],
  });

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  protected onSubmit(): void {
    const value = this.text.value.trim();
    if (value.length === 0) {
      this.text.markAsTouched();
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .createNote(this.entityType(), this.entityId(), value)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (activity) => {
          this.submitting.set(false);
          this.text.reset('');
          this.created.emit(activity);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not save the note.');
        },
      });
  }
}
