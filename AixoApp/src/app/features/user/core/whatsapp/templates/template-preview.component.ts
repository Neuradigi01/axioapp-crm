import { ChangeDetectionStrategy, Component, Input, signal } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import {
  WhatsAppTemplateButton,
  WhatsAppTemplateHeaderType,
} from './whatsapp-templates-api.service';

/**
 * WhatsApp-style bubble preview
 * (whatsapp-platform-upgrade Step 9).
 *
 * Renders a static bubble approximation of how the template will look
 * on a recipient's phone. Resolves `{{n}}` placeholders against
 * `sampleValues` so the operator sees the rendered output, not the
 * raw template syntax. Intentionally NOT pixel-perfect — WhatsApp's
 * renderer drifts across iOS / Android / Web; we promise "shape and
 * structure", not exact match.
 */
@Component({
  selector: 'app-template-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    <div
      class="flex flex-col rounded-2xl border border-subtle bg-[#e5ddd5] p-4 shadow-inner"
      style="min-height: 320px; background-image: radial-gradient(circle, rgba(0,0,0,0.04) 1px, transparent 1px); background-size: 12px 12px;"
    >
      <p class="mb-2 text-center text-[10px] font-medium uppercase tracking-wide text-muted">
        Preview
      </p>

      <div class="flex justify-start">
        <div
          class="max-w-[85%] rounded-2xl rounded-tl-sm bg-surface px-3 py-2 text-sm text-default shadow-sm"
        >
          @if (headerType === 'TEXT' && headerText) {
            <p class="mb-1 text-sm font-bold text-default">
              {{ resolved(headerText) }}
            </p>
          } @else if (headerType === 'IMAGE') {
            <div class="mb-2 flex h-32 items-center justify-center rounded-lg bg-surface-2">
              <lucide-icon name="image" class="h-8 w-8 text-faint" />
            </div>
          } @else if (headerType === 'VIDEO') {
            <div class="mb-2 flex h-32 items-center justify-center rounded-lg bg-surface-2">
              <lucide-icon name="video" class="h-8 w-8 text-faint" />
            </div>
          } @else if (headerType === 'DOCUMENT') {
            <div class="mb-2 flex h-16 items-center gap-2 rounded-lg bg-surface-2 px-3">
              <lucide-icon name="file-text" class="h-6 w-6 text-muted" />
              <span class="text-xs text-muted">document.pdf</span>
            </div>
          }

          @if (body) {
            <p class="whitespace-pre-wrap break-words text-sm">
              {{ resolved(body) }}
            </p>
          } @else {
            <p class="text-xs italic text-faint">Body text will appear here…</p>
          }

          @if (footerText) {
            <p class="mt-1 text-xs text-muted">
              {{ footerText }}
            </p>
          }

          <p class="mt-1 flex items-center justify-end gap-1 text-[10px] text-faint">
            <span>{{ currentTime() }}</span>
            <lucide-icon name="check-check" class="h-3 w-3 text-sky-500" />
          </p>
        </div>
      </div>

      @if (buttons && buttons.length > 0) {
        <div class="mt-1 flex flex-col gap-1">
          @for (b of buttons; track b.text) {
            <button
              type="button"
              class="rounded-2xl rounded-tl-sm bg-surface px-3 py-2 text-center text-sm font-medium text-[#00a884] shadow-sm"
              disabled
            >
              @if (b.type === 'URL') {
                <lucide-icon name="arrow-right" class="mr-1 inline h-3.5 w-3.5" />
              } @else if (b.type === 'PHONE_NUMBER') {
                <lucide-icon name="phone" class="mr-1 inline h-3.5 w-3.5" />
              } @else {
                <lucide-icon name="corner-up-left" class="mr-1 inline h-3.5 w-3.5" />
              }
              {{ b.text }}
            </button>
          }
        </div>
      }
    </div>
  `,
})
export class TemplatePreviewComponent {
  @Input() body = '';
  @Input() headerType: WhatsAppTemplateHeaderType | null = null;
  @Input() headerText: string | null = null;
  @Input() footerText: string | null = null;
  @Input() buttons: WhatsAppTemplateButton[] = [];
  /** Map of `{1: "Asha", 2: "30%"}` — substituted into `{{n}}` slots
   *  on the body + TEXT header. Missing entries fall back to
   *  `{{n}}` so the operator sees what didn't resolve. */
  @Input() sampleValues: Record<number, string> = {};

  protected readonly currentTime = signal(
    new Date().toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    }),
  );

  protected resolved(text: string): string {
    return text.replace(/\{\{(\d+)\}\}/g, (match, n) => {
      const value = this.sampleValues[Number(n)];
      return value && value.trim().length > 0 ? value : match;
    });
  }
}
