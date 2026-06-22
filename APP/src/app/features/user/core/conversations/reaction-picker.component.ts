import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
} from '@angular/core';

const DEFAULT_EMOJIS = ['👍', '❤️', '😂', '😮', '😢', '🙏'];

const MORE_EMOJIS = [
  '🔥', '🎉', '👏', '✅', '❌', '💯',
  '🤔', '😎', '😡', '🥳', '🤝', '💔',
];

/**
 * Inline reaction picker (whatsapp-platform-upgrade Step 7).
 *
 * Shows the 6 default WhatsApp-style reactions on a single row plus a
 * "+" toggle that reveals a second row of common alternates. Tapping
 * the same emoji the caller already reacted with emits `null` so the
 * parent can dispatch the "remove" call (matches Meta's "empty emoji
 * removes" Cloud-API pattern).
 */
@Component({
  selector: 'app-reaction-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="inline-flex flex-col gap-1 rounded-2xl border border-zinc-200 bg-white p-1.5 shadow-md"
      (click)="$event.stopPropagation()"
    >
      <div class="flex items-center gap-0.5">
        @for (emoji of defaults; track emoji) {
          <button
            type="button"
            (click)="pickEmoji(emoji)"
            [class]="
              'inline-flex h-8 w-8 items-center justify-center rounded-full text-lg transition hover:bg-zinc-100 ' +
              (existing === emoji ? 'bg-zinc-100 ring-1 ring-zinc-300' : '')
            "
            [attr.aria-label]="'React with ' + emoji"
          >
            {{ emoji }}
          </button>
        }
        <button
          type="button"
          (click)="toggleMore()"
          class="inline-flex h-8 w-8 items-center justify-center rounded-full text-xs font-medium text-zinc-500 transition hover:bg-zinc-100"
          aria-label="More reactions"
        >
          {{ moreOpen() ? '−' : '+' }}
        </button>
      </div>
      @if (moreOpen()) {
        <div class="grid grid-cols-6 gap-0.5">
          @for (emoji of more; track emoji) {
            <button
              type="button"
              (click)="pickEmoji(emoji)"
              [class]="
                'inline-flex h-8 w-8 items-center justify-center rounded-full text-lg transition hover:bg-zinc-100 ' +
                (existing === emoji ? 'bg-zinc-100 ring-1 ring-zinc-300' : '')
              "
              [attr.aria-label]="'React with ' + emoji"
            >
              {{ emoji }}
            </button>
          }
        </div>
      }
    </div>
  `,
})
export class ReactionPickerComponent {
  /** The caller's current reaction on this message, if any. Tapping
   *  the same emoji again emits `null` to signal removal. */
  @Input() existing: string | null = null;

  /** Emits the picked emoji, or `null` when the caller tapped their
   *  current reaction to remove it. */
  @Output() readonly pick = new EventEmitter<string | null>();

  protected readonly defaults = DEFAULT_EMOJIS;
  protected readonly more = MORE_EMOJIS;
  protected readonly moreOpen = signal(false);

  protected pickEmoji(emoji: string): void {
    this.pick.emit(this.existing === emoji ? null : emoji);
  }

  protected toggleMore(): void {
    this.moreOpen.update((v) => !v);
  }
}
