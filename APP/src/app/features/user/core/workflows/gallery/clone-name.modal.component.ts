import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { WorkflowGalleryEntry } from '../workflows-api.service';

/**
 * Naming modal — opens after the operator clicks "Use this template"
 * (either from a card or from inside the preview modal). Shows a
 * single text input pre-filled with "Copy of <template name>", a
 * Cancel + Create button.
 *
 * Submits the chosen name back to the parent via `(confirm)`. Empty
 * input falls back to "Copy of <template name>" — the backend
 * defaults to the same value when no name is supplied.
 */

@Component({
  selector: 'app-clone-name-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './clone-name.modal.component.html',
})
export class CloneNameModalComponent {
  readonly entry = input.required<WorkflowGalleryEntry>();
  readonly busy = input<boolean>(false);
  readonly cancel = output<void>();
  readonly confirm = output<{ name: string }>();

  readonly name = signal('');

  readonly defaultName = computed(() => `Copy of ${this.entry().name}`);

  constructor() {
    effect(() => {
      // Re-seed the input whenever the entry changes.
      this.name.set(this.defaultName());
    });
  }

  onSubmit(event: Event): void {
    event.preventDefault();
    if (this.busy()) return;
    const value = this.name().trim() || this.defaultName();
    this.confirm.emit({ name: value });
  }
}
