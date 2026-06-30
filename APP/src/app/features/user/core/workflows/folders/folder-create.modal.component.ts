import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
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
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { WorkflowFolder, WorkflowsApiService } from '../workflows-api.service';

/**
 * Modal for creating a workflow folder. Mounted by the folders
 * sidebar; the parent passes the existing folders so the parent
 * picker can render. Two-level nesting is the practical ceiling
 * (master sidebar UI can't visually distinguish deeper trees) — the
 * picker only offers depth-0 folders as parents.
 */

@Component({
  selector: 'app-workflow-folder-create-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, ReactiveFormsModule, LucideAngularModule],
  templateUrl: './folder-create.modal.component.html',
})
export class FolderCreateModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(WorkflowsApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Existing folders — used to render the parent picker. */
  readonly folders = input<WorkflowFolder[]>([]);

  readonly created = output<WorkflowFolder>();
  readonly cancelled = output<void>();

  protected readonly saving = signal<boolean>(false);
  protected readonly saveError = signal<string | null>(null);

  protected readonly form = this.fb.group({
    name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(120)],
    }),
    parent_folder_id: this.fb.control<string | ''>('', { nonNullable: true }),
  });

  protected onCancel(): void {
    if (this.saving()) return;
    this.cancelled.emit();
  }

  /** Returns folders that themselves have no parent — depth limit. */
  protected get parentCandidates(): WorkflowFolder[] {
    return this.folders().filter((f) => f.parent_folder_id === null);
  }

  protected save(): void {
    if (this.form.invalid || this.saving()) return;
    this.saving.set(true);
    this.saveError.set(null);

    const raw = this.form.getRawValue();
    this.api
      .createFolder({
        name: raw.name.trim(),
        parent_folder_id: raw.parent_folder_id || null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (folder) => {
          this.saving.set(false);
          this.created.emit(folder);
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.saveError.set(extractApiError(err) ?? 'Could not create folder.');
        },
      });
  }
}
