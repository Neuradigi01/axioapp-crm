import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { LucideAngularModule } from 'lucide-angular';

import type { TemplateChannel, WhatsAppTemplateButton } from '../templates-api.service';

/**
 * Generic preview pane — resolves dot-path `{{a.b.c}}` against a
 * fixed sample context and renders one of two shapes:
 *
 *   - WhatsApp: chat-bubble approximation in WhatsApp's own light / dark
 *     palette, with header / body / footer / buttons and WhatsApp text
 *     formatting (*bold*, _italic_, ~strike~, ```mono```).
 *   - Email: subject + the HTML design rendered in a sandboxed iframe
 *     (scripts never run), falling back to the plain-text body.
 *
 * Variables with no sample value are highlighted rather than silently
 * dropped, so a typo like `{{contact.frist_name}}` is visible.
 *
 * SMS / FB / IG / push fall through to a simple body-only card.
 *
 * The sample context is hard-coded — the test-send modal is where the
 * operator picks real recipient data.
 */
const SAMPLE_CONTEXT: Record<string, Record<string, string>> = {
  contact: {
    first_name: 'Asha',
    last_name: 'Mehta',
    full_name: 'Asha Mehta',
    email: 'asha@example.com',
    phone: '+91 98765 43210',
  },
  org: {
    name: 'Acme Furniture',
    support_email: 'support@acme.example',
    support_phone: '+91 80000 00000',
    address: '12 Brigade Road, Bengaluru',
    website: 'https://acme.example',
  },
  sender: {
    name: 'Rahul Patel',
    email: 'rahul@acme.example',
    role: 'Sales Manager',
    signature: 'Rahul Patel · Acme Furniture',
  },
  lead: {
    source: 'Website',
    status: 'Qualified',
    score: '78',
    estimated_value: '₹45,000',
    owner_name: 'Rahul Patel',
  },
  user: {
    full_name: 'Asha Mehta',
    email: 'asha@example.com',
    role: 'Owner',
  },
  appointment: {
    scheduled_at: 'Mon, 15 Jul · 11:00 AM',
    location: 'Bengaluru Showroom',
    notes: 'Bring fabric swatches',
  },
  quote: {
    id: 'Q-2026-1042',
    total_amount: '₹45,000',
    currency: 'INR',
    expires_at: '12 Jul 2026',
    pdf_url: 'https://acme.example/quotes/1042.pdf',
  },
  invoice: {
    id: 'INV-2026-0421',
    total_amount: '₹45,000',
    currency: 'INR',
    due_date: '30 Jul 2026',
    pdf_url: 'https://acme.example/invoices/0421.pdf',
  },
};

const VAR_RE = /\{\{\s*([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*)\s*\}\}/g;

/** WhatsApp inline formatting markers: ```mono```, *bold*, _italic_, ~strike~. */
const WA_FORMAT_RE = /(```[^`]+```|\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~)/g;

/** One rendered run of preview text. */
interface PreviewSegment {
  text: string;
  bold?: boolean;
  italic?: boolean;
  strike?: boolean;
  mono?: boolean;
  /** A `{{variable}}` with no sample value — shown highlighted. */
  unknown?: boolean;
}

function lookupSample(path: string): string | null {
  let cursor: unknown = SAMPLE_CONTEXT;
  for (const seg of path.split('.')) {
    if (cursor !== null && typeof cursor === 'object' && seg in (cursor as object)) {
      cursor = (cursor as Record<string, unknown>)[seg];
    } else {
      return null;
    }
  }
  return typeof cursor === 'string' ? cursor : null;
}

/** Split text into plain runs and unknown-variable runs, substituting
 *  sample values for the variables we know. */
function resolveSegments(text: string): PreviewSegment[] {
  const out: PreviewSegment[] = [];
  let last = 0;
  for (const m of text.matchAll(VAR_RE)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push({ text: text.slice(last, idx) });
    const value = lookupSample(m[1]);
    out.push(value === null ? { text: m[0], unknown: true } : { text: value });
    last = idx + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}

/** Apply WhatsApp inline formatting inside the plain runs. */
function applyWaFormatting(segments: PreviewSegment[]): PreviewSegment[] {
  const out: PreviewSegment[] = [];
  for (const seg of segments) {
    if (seg.unknown) {
      out.push(seg);
      continue;
    }
    for (const part of seg.text.split(WA_FORMAT_RE)) {
      if (!part) continue;
      if (part.startsWith('```') && part.endsWith('```') && part.length > 6) {
        out.push({ text: part.slice(3, -3), mono: true });
      } else if (part.length > 2 && part[0] === '*' && part.endsWith('*')) {
        out.push({ text: part.slice(1, -1), bold: true });
      } else if (part.length > 2 && part[0] === '_' && part.endsWith('_')) {
        out.push({ text: part.slice(1, -1), italic: true });
      } else if (part.length > 2 && part[0] === '~' && part.endsWith('~')) {
        out.push({ text: part.slice(1, -1), strike: true });
      } else {
        out.push({ text: part });
      }
    }
  }
  return out;
}

@Component({
  selector: 'app-preview-pane',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, NgTemplateOutlet],
  template: `
    <ng-template #runs let-segments>
      @for (seg of segments; track $index) {
        @if (seg.unknown) {
          <span
            class="rounded bg-amber-400/30 px-0.5 font-mono text-[0.85em] text-amber-800 dark:text-amber-200"
            title="No sample value — check the variable name"
            >{{ seg.text }}</span
          >
        } @else {
          <span
            [class.font-semibold]="seg.bold"
            [class.italic]="seg.italic"
            [class.line-through]="seg.strike"
            [class.font-mono]="seg.mono"
            >{{ seg.text }}</span
          >
        }
      }
    </ng-template>

    @switch (channel()) {
      @case ('whatsapp') {
        <div
          class="rounded-2xl border border-subtle bg-[#efeae2] p-4 shadow-inner dark:bg-[#0b141a]"
          style="min-height: 320px; background-image: radial-gradient(circle, rgba(127,127,127,0.08) 1px, transparent 1px); background-size: 12px 12px;"
        >
          <p
            class="mb-2 text-center text-[10px] font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400"
          >
            Preview
          </p>
          <div class="flex flex-col items-start gap-1">
            <div
              class="max-w-[85%] overflow-hidden rounded-2xl rounded-tl-sm bg-white text-sm text-zinc-900 shadow-sm dark:bg-[#202c33] dark:text-zinc-100"
            >
              @if (waHeaderType() === 'text' && waHeaderText()) {
                <p class="px-3 pt-2 text-sm font-semibold">
                  <ng-container
                    [ngTemplateOutlet]="runs"
                    [ngTemplateOutletContext]="{ $implicit: headerSegments() }"
                  />
                </p>
              } @else if (waHeaderType()) {
                <div
                  class="flex h-24 items-center justify-center gap-1.5 bg-zinc-200 text-[10px] uppercase tracking-wide text-zinc-500 dark:bg-[#2a3942] dark:text-zinc-400"
                >
                  <lucide-icon
                    [name]="
                      waHeaderType() === 'image'
                        ? 'image'
                        : waHeaderType() === 'video'
                          ? 'video'
                          : 'file-text'
                    "
                    size="14"
                  />
                  {{ waHeaderType() }} header
                </div>
              }

              @if (body()) {
                <p class="whitespace-pre-wrap break-words px-3 pt-2 text-sm">
                  <ng-container
                    [ngTemplateOutlet]="runs"
                    [ngTemplateOutletContext]="{ $implicit: waBodySegments() }"
                  />
                </p>
              } @else {
                <p class="px-3 pt-2 text-xs italic text-zinc-400">Body text will appear here…</p>
              }

              @if (waFooter()) {
                <p class="px-3 pt-1 text-[11px] text-zinc-500 dark:text-zinc-400">
                  {{ waFooter() }}
                </p>
              }
              <p class="px-3 pb-1.5 text-right text-[10px] text-zinc-500 dark:text-zinc-400">
                12:30
              </p>
            </div>

            @if (waButtons().length > 0) {
              <div class="flex w-full max-w-[85%] flex-col gap-1">
                @for (btn of waButtons(); track $index) {
                  <div
                    class="flex items-center justify-center gap-1.5 rounded-lg bg-white px-3 py-2 text-sm font-medium text-[#027eb5] shadow-sm dark:bg-[#202c33] dark:text-[#53bdeb]"
                  >
                    @if (btn.type === 'url') {
                      <lucide-icon name="external-link" size="14" aria-hidden="true"></lucide-icon>
                    } @else if (btn.type === 'phone_number') {
                      <lucide-icon name="phone" size="14" aria-hidden="true"></lucide-icon>
                    } @else {
                      <lucide-icon name="corner-up-left" size="14" aria-hidden="true"></lucide-icon>
                    }
                    <span>{{ btn.text || '(button label)' }}</span>
                  </div>
                }
              </div>
            }
          </div>
        </div>
      }
      @case ('email') {
        <div class="rounded-xl border border-subtle bg-surface p-4 shadow-sm">
          <p class="mb-2 text-[10px] font-medium uppercase tracking-wide text-muted">Preview</p>
          @if (subject()) {
            <div class="mb-2 border-b border-subtle pb-2">
              <p class="text-[10px] uppercase tracking-wide text-faint">Subject</p>
              <p class="text-sm font-semibold text-default">
                <ng-container
                  [ngTemplateOutlet]="runs"
                  [ngTemplateOutletContext]="{ $implicit: subjectSegments() }"
                />
              </p>
            </div>
          }
          @if (emailHtmlDoc(); as doc) {
            <!-- The design renders in a sandboxed iframe: no scripts, a
                 unique origin, and its CSS can't leak into the app. -->
            <iframe
              sandbox=""
              [srcdoc]="doc"
              title="Email preview"
              class="h-[420px] w-full rounded-md border border-subtle bg-white"
            ></iframe>
          } @else if (body()) {
            <p class="whitespace-pre-wrap break-words text-sm text-default">
              <ng-container
                [ngTemplateOutlet]="runs"
                [ngTemplateOutletContext]="{ $implicit: bodySegments() }"
              />
            </p>
          } @else {
            <p class="text-xs italic text-faint">Body will appear here as you type…</p>
          }
        </div>
      }
      @default {
        <div class="rounded-xl border border-subtle bg-surface p-4 shadow-sm">
          <p class="mb-2 text-[10px] font-medium uppercase tracking-wide text-muted">Preview</p>
          @if (body()) {
            <p class="whitespace-pre-wrap break-words text-sm text-default">
              <ng-container
                [ngTemplateOutlet]="runs"
                [ngTemplateOutletContext]="{ $implicit: bodySegments() }"
              />
            </p>
          } @else {
            <p class="text-xs italic text-faint">Body will appear here…</p>
          }
        </div>
      }
    }
  `,
})
export class PreviewPaneComponent {
  private readonly sanitizer = inject(DomSanitizer);

  readonly channel = input.required<TemplateChannel>();
  readonly subject = input<string | null>(null);
  readonly body = input<string>('');
  /** Email HTML design — rendered in a sandboxed iframe when present. */
  readonly bodyHtml = input<string | null>(null);
  // WhatsApp-specific extras. All optional — the preview falls back
  // to the plain body-only bubble when nothing is supplied so non-WA
  // channels are unaffected.
  readonly waHeaderType = input<'' | 'text' | 'image' | 'video' | 'document'>('');
  readonly waHeaderText = input<string>('');
  readonly waFooter = input<string>('');
  readonly waButtons = input<WhatsAppTemplateButton[]>([]);

  protected readonly subjectSegments = computed(() => resolveSegments(this.subject() ?? ''));
  protected readonly bodySegments = computed(() => resolveSegments(this.body()));
  protected readonly waBodySegments = computed(() =>
    applyWaFormatting(resolveSegments(this.body())),
  );
  protected readonly headerSegments = computed(() =>
    applyWaFormatting(resolveSegments(this.waHeaderText())),
  );

  /** The HTML design with sample values filled in. Trusted for `srcdoc`
   *  only because the iframe is fully sandboxed (`sandbox=""`: no
   *  scripts, unique origin) and the body is server-sanitised on save. */
  protected readonly emailHtmlDoc = computed<SafeHtml | null>(() => {
    const html = (this.bodyHtml() ?? '').trim();
    if (!html) return null;
    const filled = html.replace(VAR_RE, (match, path: string) => lookupSample(path) ?? match);
    return this.sanitizer.bypassSecurityTrustHtml(filled);
  });
}
