import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Input,
  Output,
  EventEmitter,
  ViewChild,
  AfterViewInit,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

/**
 * Text-input prompt dialog — the input-taking counterpart to
 * `ConfirmDialogComponent`. Renders a small modal with a single
 * `<input type="text">` field, `Cancel` / `Confirm` buttons, and an
 * optional inline error slot. Kept next to `ConfirmDialogComponent`
 * so the two share styling primitives and both mount through the same
 * `<app-confirm-dialog-host />` at the app shell.
 *
 * Usage from a service / caller:
 *
 *   <app-prompt-dialog
 *     [title]="'Clone workflow'"
 *     [body]="'Give the copy a name…'"
 *     [placeholder]="'Workflow name'"
 *     [initialValue]="row.name + ' (copy)'"
 *     [confirmLabel]="'Clone'"
 *     (confirm)="onConfirm($event)"
 *     (cancel)="onCancel()"
 *   />
 */
@Component({
  selector: 'app-prompt-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  templateUrl: './prompt-dialog.component.html',
})
export class PromptDialogComponent implements AfterViewInit {
  @Input() title = 'Enter a value';
  @Input() body: string | null = null;
  @Input() placeholder = '';
  @Input() confirmLabel = 'Confirm';
  @Input() cancelLabel = 'Cancel';
  @Input() submitting = false;
  @Input() error: string | null = null;

  /** Two-way seed for the input. Only read on mount; subsequent
   *  changes come from the field itself. */
  @Input() set initialValue(v: string) {
    this.value.set(v ?? '');
  }

  @Output() readonly confirm = new EventEmitter<string>();
  @Output() readonly cancel = new EventEmitter<void>();

  @ViewChild('input', { static: true }) input!: ElementRef<HTMLInputElement>;

  protected readonly value = signal('');

  ngAfterViewInit(): void {
    // Auto-focus + select-all so the operator can either accept the
    // default (Enter) or start typing to overwrite immediately.
    queueMicrotask(() => {
      const el = this.input?.nativeElement;
      if (!el) return;
      el.focus();
      el.select();
    });
  }

  protected onSubmit(event: Event): void {
    event.preventDefault();
    if (this.submitting) return;
    const trimmed = this.value().trim();
    if (!trimmed) return;
    this.confirm.emit(trimmed);
  }
}
