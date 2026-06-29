import { CommonModule } from '@angular/common';
import {
  CdkDragDrop,
  DragDropModule,
  moveItemInArray,
} from '@angular/cdk/drag-drop';
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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  WorkflowFolder,
  WorkflowsApiService,
} from '../workflows-api.service';

/**
 * Folders sidebar. Drives the list page's folder filter. Top-level
 * folders are draggable to reorder (CDK drag-drop) — the new
 * `display_order` is persisted via PATCH /workflows/folders/{id}.
 *
 * Renaming uses an inline contenteditable-like flow: double-click a
 * row to swap the label for an `<input>`, blur or Enter saves, Esc
 * cancels.
 */


@Component({
  selector: 'app-workflow-folders-sidebar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, DragDropModule, LucideAngularModule],
  templateUrl: './folders-sidebar.component.html',
})
export class FoldersSidebarComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly folders = input<WorkflowFolder[]>([]);
  readonly selectedFolderId = input<string | null>(null);
  readonly canWrite = input<boolean>(false);

  readonly folderSelected = output<string | null>();
  readonly newFolderRequested = output<void>();
  readonly foldersReordered = output<WorkflowFolder[]>();

  protected readonly editingId = signal<string | null>(null);
  protected readonly editingValue = signal<string>('');
  protected readonly mutationError = signal<string | null>(null);

  /** Top-level folders sorted by display_order. */
  protected readonly topLevel = computed<WorkflowFolder[]>(() =>
    this.folders()
      .filter((f) => f.parent_folder_id === null)
      .slice()
      .sort((a, b) => a.display_order - b.display_order),
  );

  protected childrenOf(parentId: string): WorkflowFolder[] {
    return this.folders()
      .filter((f) => f.parent_folder_id === parentId)
      .slice()
      .sort((a, b) => a.display_order - b.display_order);
  }

  protected selectAll(): void {
    this.folderSelected.emit(null);
  }

  protected select(id: string): void {
    if (this.editingId() === id) return;
    this.folderSelected.emit(id);
  }

  protected onNewFolder(): void {
    this.newFolderRequested.emit();
  }

  // --- rename -------------------------------------------------------

  protected beginRename(folder: WorkflowFolder, event: MouseEvent): void {
    if (!this.canWrite()) return;
    event.stopPropagation();
    this.editingId.set(folder.id);
    this.editingValue.set(folder.name);
  }

  protected onRenameInput(value: string): void {
    this.editingValue.set(value);
  }

  protected commitRename(folder: WorkflowFolder): void {
    const next = this.editingValue().trim();
    this.editingId.set(null);
    if (!next || next === folder.name) return;
    this.api
      .patchFolder(folder.id, { name: next })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          const merged = this.folders().map((f) =>
            f.id === folder.id ? updated : f,
          );
          this.foldersReordered.emit(merged);
        },
        error: (err: HttpErrorResponse) => {
          this.mutationError.set(
            extractApiError(err) ?? 'Could not rename folder.',
          );
        },
      });
  }

  protected cancelRename(): void {
    this.editingId.set(null);
  }

  // --- reorder ------------------------------------------------------

  protected onDrop(event: CdkDragDrop<WorkflowFolder[]>): void {
    if (!this.canWrite()) return;
    if (event.previousIndex === event.currentIndex) return;
    const reordered = this.topLevel().slice();
    moveItemInArray(reordered, event.previousIndex, event.currentIndex);

    // Persist the new display_order for each top-level row.
    reordered.forEach((folder, index) => {
      if (folder.display_order === index) return;
      this.api
        .patchFolder(folder.id, { display_order: index })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          error: (err: HttpErrorResponse) => {
            this.mutationError.set(
              extractApiError(err) ?? 'Could not reorder folders.',
            );
          },
        });
    });

    // Optimistic local-state push so the parent reflects the new order
    // before the PATCHes resolve.
    const merged = this.folders().map((f) => {
      const idx = reordered.findIndex((r) => r.id === f.id);
      return idx === -1 ? f : { ...f, display_order: idx };
    });
    this.foldersReordered.emit(merged);
  }

  protected onDelete(folder: WorkflowFolder, event: MouseEvent): void {
    event.stopPropagation();
    if (!this.canWrite()) return;
    if (!confirm(`Delete folder "${folder.name}"? It must be empty.`)) {
      return;
    }
    this.api
      .deleteFolder(folder.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          const next = this.folders().filter((f) => f.id !== folder.id);
          this.foldersReordered.emit(next);
          if (this.selectedFolderId() === folder.id) {
            this.folderSelected.emit(null);
          }
        },
        error: (err: HttpErrorResponse) => {
          this.mutationError.set(
            extractApiError(err) ?? 'Could not delete folder.',
          );
        },
      });
  }

  protected trackById = (_: number, f: WorkflowFolder) => f.id;
}
