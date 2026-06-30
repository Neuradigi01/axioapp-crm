import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  effect,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';


/**
 * Save-change-note modal — pops when the operator clicks Save Draft
 * after a non-trivial graph edit, asks for a one-line "describe this
 * change". Empty input falls back to `Edited at <time>` so the
 * version row always has SOMETHING.
 *
 * The modal does NOT submit anything itself — it bubbles the note
 * up to the canvas page, which then includes it in the
 * `PATCH /workflows/{id}` payload's `change_note` field.
 */


function defaultNote(now: Date = new Date()): string {
  const hh = now.getHours().toString().padStart(2, '0');
  const mm = now.getMinutes().toString().padStart(2, '0');
  return `Edited at ${hh}:${mm}`;
}


@Component({
  selector: 'app-save-change-note-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './save-change-note.modal.component.html',
})
export class SaveChangeNoteModalComponent {
  /** Externally controlled visibility — the canvas page sets this
   *  true when Save Draft fires and resets after submit/cancel. */
  readonly open = input<boolean>(false);
  readonly busy = input<boolean>(false);

  readonly cancel = output<void>();
  readonly confirm = output<{ note: string }>();

  readonly note = signal('');

  constructor() {
    effect(() => {
      if (this.open()) {
        // Re-seed the placeholder when the modal pops.
        this.note.set('');
      }
    });
  }

  onSubmit(event: Event): void {
    event.preventDefault();
    if (this.busy()) return;
    const value = this.note().trim() || defaultNote();
    this.confirm.emit({ note: value });
  }

  fallbackPlaceholder(): string {
    return defaultNote();
  }
}
