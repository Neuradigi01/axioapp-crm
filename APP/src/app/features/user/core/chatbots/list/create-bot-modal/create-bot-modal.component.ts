import { CommonModule } from '@angular/common';
import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  Output,
  ViewChild,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

/**
 * "Name your new bot" prompt modal. Replaces the native
 * `window.prompt` on the chatbots list so the create flow uses the
 * same styled surfaces as the rest of the app.
 *
 * Emits `{ name, description }` on Create — description is optional
 * and is trimmed to `null` when blank so the backend stores NULL
 * rather than an empty string.
 */
@Component({
  selector: 'app-chatbot-create-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      (click)="onBackdropClick($event)"
    >
      <div
        class="bg-surface border border-subtle rounded-xl w-[480px] max-w-[92vw] shadow-2xl"
        (click)="$event.stopPropagation()"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-bot-title"
      >
        <header class="flex items-center gap-3 px-5 py-4 border-b border-subtle">
          <span
            class="w-8 h-8 rounded-lg bg-accent-soft text-accent inline-flex items-center justify-center"
          >
            <lucide-icon name="bot" size="16"></lucide-icon>
          </span>
          <div class="flex-1">
            <h2 id="create-bot-title" class="text-sm font-semibold text-default">Create bot</h2>
            <p class="text-[11px] text-muted mt-0.5">
              Give your new bot a name and an optional short description so teammates know what it
              does at a glance.
            </p>
          </div>
          <button
            type="button"
            (click)="close.emit()"
            class="p-1.5 rounded hover:bg-surface-2 text-muted hover:text-default"
            aria-label="Close"
          >
            <lucide-icon name="x" size="16"></lucide-icon>
          </button>
        </header>

        <div class="px-5 py-5 space-y-4">
          <div class="space-y-1.5">
            <label
              for="new-bot-name"
              class="block text-[11px] font-medium text-muted uppercase tracking-wide"
            >
              Bot name
            </label>
            <input
              #nameInput
              id="new-bot-name"
              type="text"
              [ngModel]="name()"
              (ngModelChange)="name.set($event); error.set(null)"
              (keydown.enter)="submit()"
              placeholder="e.g. Welcome Bot"
              maxlength="120"
              class="w-full px-3 py-2 text-sm bg-app text-default border border-subtle rounded-md focus:outline-none focus:border-accent"
            />
          </div>

          <div class="space-y-1.5">
            <label
              for="new-bot-description"
              class="flex items-center justify-between text-[11px] font-medium text-muted uppercase tracking-wide"
            >
              <span>Description</span>
              <span class="normal-case text-faint">Optional</span>
            </label>
            <textarea
              id="new-bot-description"
              rows="2"
              [ngModel]="description()"
              (ngModelChange)="description.set($event)"
              placeholder="e.g. Handles first-touch replies for pricing enquiries on WhatsApp."
              maxlength="2000"
              class="w-full px-3 py-2 text-sm bg-app text-default border border-subtle rounded-md focus:outline-none focus:border-accent resize-none"
            ></textarea>
          </div>

          @if (error()) {
            <p class="text-[12px] text-red-500">{{ error() }}</p>
          }
        </div>

        <footer class="flex justify-end gap-2 px-5 py-3 border-t border-subtle">
          <button
            type="button"
            (click)="close.emit()"
            [disabled]="submitting"
            class="px-3.5 py-1.5 text-xs font-medium text-muted hover:text-default disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            (click)="submit()"
            [disabled]="submitting || !name().trim()"
            class="px-3.5 py-1.5 text-xs font-semibold bg-accent-soft text-accent hover:brightness-110 rounded-md disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {{ submitting ? 'Creating…' : 'Create bot' }}
          </button>
        </footer>
      </div>
    </div>
  `,
})
export class ChatbotCreateModalComponent implements AfterViewInit {
  @Input() submitting = false;
  @Input() set errorMessage(msg: string | null) {
    this.error.set(msg);
  }

  @Output() readonly create = new EventEmitter<{
    name: string;
    description: string | null;
  }>();
  @Output() readonly close = new EventEmitter<void>();

  @ViewChild('nameInput') private nameInputRef?: ElementRef<HTMLInputElement>;

  readonly name = signal<string>('');
  readonly description = signal<string>('');
  readonly error = signal<string | null>(null);

  ngAfterViewInit(): void {
    queueMicrotask(() => this.nameInputRef?.nativeElement.focus());
  }

  submit(): void {
    const trimmedName = this.name().trim();
    if (!trimmedName) {
      this.error.set('Please enter a name.');
      return;
    }
    const trimmedDescription = this.description().trim();
    this.create.emit({
      name: trimmedName,
      description: trimmedDescription === '' ? null : trimmedDescription,
    });
  }

  onBackdropClick(evt: MouseEvent): void {
    if (evt.target === evt.currentTarget && !this.submitting) this.close.emit();
  }
}
