import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  input,
} from '@angular/core';

export interface StickerAttachment {
  type: 'sticker';
  id?: string;
  mime_type?: string | null;
  animated?: boolean;
  sha256?: string | null;
}

/**
 * Sticker bubble (whatsapp-platform-upgrade Step 28).
 *
 * Meta stickers come through as a media reference (`id`) on the
 * webhook — we don't fetch the actual image binary here (would
 * need the same Meta `/media/{id}` round-trip the regular image
 * media pipeline uses, plus on-demand auth). For the bubble we
 * render a styled placeholder with the "Sticker" pill + a small
 * animated indicator when applicable — operators can still see
 * the sticker on their phone if they need the actual image.
 *
 * A future enhancement would proxy the Meta `/media/{id}` through
 * our `/api/v1/conversations/.../media/{id}` endpoint (same
 * pattern as Step 5 image inbound) — out of scope here.
 */
@Component({
  selector: 'app-sticker-bubble',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    <div class="flex flex-col items-start gap-1">
      <div
        class="flex h-24 w-24 items-center justify-center rounded-md bg-zinc-50 text-3xl ring-1 ring-zinc-200"
      >
        🟦
      </div>
      <span
        class="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-600 ring-1 ring-zinc-200"
      >
        Sticker
        @if (sticker().animated) {
          <span class="text-amber-700">· animated</span>
        }
      </span>
    </div>
  `,
})
export class StickerBubbleComponent {
  readonly sticker = input.required<StickerAttachment>();
}
