import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { TriggerConfig } from '../../chatbots-api.service';

/**
 * Bot-trigger configuration modal (tasks/chatbot-builder Step 13 /
 * mockup.html).
 *
 * Opens from the always-present trigger card at the top of the
 * canvas. Emits `(save)` with the assembled TriggerConfig; the
 * builder page hands it off to `canvasState.setTriggerConfig`.
 */
@Component({
  selector: 'app-chatbot-trigger-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      (click)="onBackdropClick($event)"
    >
      <div
        class="bg-surface border border-subtle rounded-xl w-[520px] max-w-[92vw] shadow-2xl"
        (click)="$event.stopPropagation()"
      >
        <header class="flex items-center gap-3 px-5 py-4 border-b border-subtle">
          <span
            class="w-8 h-8 rounded-lg bg-accent-soft text-accent inline-flex items-center justify-center"
          >
            <lucide-icon name="zap" size="16"></lucide-icon>
          </span>
          <div class="flex-1">
            <h2 class="text-sm font-semibold text-default">Trigger</h2>
            <p class="text-[11px] text-muted mt-0.5">When should this bot start?</p>
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
          <div>
            <label class="block text-[11px] font-medium text-muted mb-1.5 uppercase tracking-wide"
              >Channel</label
            >
            <select
              [ngModel]="channel()"
              (ngModelChange)="channel.set($event)"
              class="w-full px-3 py-2 text-sm bg-app text-default border border-subtle rounded-md focus:outline-none focus:border-accent"
            >
              <option value="any">Any channel (WhatsApp + Email)</option>
              <option value="whatsapp">WhatsApp only</option>
              <option value="email">Email only</option>
            </select>
          </div>

          <div>
            <label class="block text-[11px] font-medium text-muted mb-1.5 uppercase tracking-wide"
              >Match mode</label
            >
            <select
              [ngModel]="mode()"
              (ngModelChange)="mode.set($event)"
              class="w-full px-3 py-2 text-sm bg-app text-default border border-subtle rounded-md focus:outline-none focus:border-accent"
            >
              <option value="any">Any inbound message (no filter)</option>
              <option value="keyword">Keyword match</option>
              <option value="regex">Regex pattern</option>
            </select>
            <p class="text-[11px] text-muted mt-1">
              Keyword match covers most bots. Use regex only for advanced patterns.
            </p>
          </div>

          @if (mode() === 'keyword') {
            <div>
              <label class="block text-[11px] font-medium text-muted mb-1.5 uppercase tracking-wide"
                >Keywords</label
              >
              <div
                class="flex flex-wrap gap-1.5 p-2 bg-app border border-subtle rounded-md min-h-[38px]"
              >
                @for (kw of keywords(); track kw) {
                  <span
                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-accent-soft text-accent"
                  >
                    {{ kw }}
                    <button
                      type="button"
                      (click)="removeKeyword(kw)"
                      class="opacity-70 hover:opacity-100"
                      aria-label="Remove keyword"
                    >
                      ×
                    </button>
                  </span>
                }
                <input
                  #kwInput
                  type="text"
                  placeholder="Add keyword, press Enter"
                  (keydown.enter)="addKeyword(kwInput.value); kwInput.value = ''"
                  class="flex-1 min-w-[100px] bg-transparent text-xs text-default focus:outline-none"
                />
              </div>
            </div>
          }

          @if (mode() === 'regex') {
            <div>
              <label class="block text-[11px] font-medium text-muted mb-1.5 uppercase tracking-wide"
                >Regex pattern</label
              >
              <input
                type="text"
                [ngModel]="regexPattern()"
                (ngModelChange)="regexPattern.set($event)"
                placeholder="^(help|support)"
                class="w-full px-3 py-2 text-xs font-mono bg-app text-default border border-subtle rounded-md focus:outline-none focus:border-accent"
              />
              <p class="text-[11px] text-muted mt-1">
                Max 500 chars. Runs on the first 4 KB of every inbound message.
              </p>
            </div>
          }

          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-xs text-default">Case sensitive</div>
              <div class="text-[11px] text-muted">"HEY" matches "hey" when off.</div>
            </div>
            <input
              type="checkbox"
              [checked]="caseSensitive()"
              (change)="caseSensitive.set(!caseSensitive())"
              class="h-4 w-4 accent-current"
            />
          </div>

          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-xs text-default">First message only</div>
              <div class="text-[11px] text-muted">
                Fire only on the customer's first-ever message.
              </div>
            </div>
            <input
              type="checkbox"
              [checked]="firstMessageOnly()"
              (change)="firstMessageOnly.set(!firstMessageOnly())"
              class="h-4 w-4 accent-current"
            />
          </div>
        </div>

        <footer class="flex justify-end gap-2 px-5 py-3 border-t border-subtle">
          <button
            type="button"
            (click)="close.emit()"
            class="px-3.5 py-1.5 text-xs font-medium text-muted hover:text-default"
          >
            Cancel
          </button>
          <button
            type="button"
            (click)="onSave()"
            class="px-3.5 py-1.5 text-xs font-semibold bg-accent-soft text-accent hover:brightness-110 rounded-md"
          >
            Save trigger
          </button>
        </footer>
      </div>
    </div>
  `,
})
export class TriggerConfigModalComponent {
  private _initial: TriggerConfig | null = null;

  @Input({ required: true })
  set config(value: TriggerConfig) {
    this._initial = value;
    this.channel.set(value.channel);
    this.mode.set(value.mode);
    this.keywords.set([...(value.keywords ?? [])]);
    this.regexPattern.set(value.regex_pattern ?? '');
    this.caseSensitive.set(!!value.case_sensitive);
    this.firstMessageOnly.set(!!value.first_message_only);
  }

  @Output() save = new EventEmitter<TriggerConfig>();
  @Output() close = new EventEmitter<void>();

  readonly channel = signal<TriggerConfig['channel']>('any');
  readonly mode = signal<TriggerConfig['mode']>('any');
  readonly keywords = signal<string[]>([]);
  readonly regexPattern = signal<string>('');
  readonly caseSensitive = signal<boolean>(false);
  readonly firstMessageOnly = signal<boolean>(false);

  addKeyword(raw: string): void {
    const kw = (raw ?? '').trim();
    if (!kw) return;
    if (this.keywords().includes(kw)) return;
    this.keywords.update((rows) => [...rows, kw]);
  }

  removeKeyword(kw: string): void {
    this.keywords.update((rows) => rows.filter((k) => k !== kw));
  }

  onBackdropClick(evt: MouseEvent): void {
    if (evt.target === evt.currentTarget) this.close.emit();
  }

  onSave(): void {
    const cfg: TriggerConfig = {
      channel: this.channel(),
      mode: this.mode(),
      keywords: this.mode() === 'keyword' ? this.keywords() : [],
      regex_pattern: this.mode() === 'regex' ? this.regexPattern().trim() || null : null,
      case_sensitive: this.caseSensitive(),
      first_message_only: this.firstMessageOnly(),
    };
    this.save.emit(cfg);
  }
}
