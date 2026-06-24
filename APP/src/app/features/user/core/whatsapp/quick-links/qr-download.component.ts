import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { QuickLink, QuickLinksService } from './quick-links.service';

/**
 * QR preview + download controls for a single quick-link (Step 26).
 *
 * The PNG preview is rendered by the backend (`qrcode[pil]`) so
 * what you see in the UI is exactly what scans in WhatsApp. Three
 * downloads are exposed:
 *
 *   * PNG at 512 px (default) — for screen + small print.
 *   * PNG at 1024 px — for large-format print (billboards, posters).
 *   * SVG — vector, scales without rasterisation; preferred for any
 *     final print job.
 *
 * The "Copy link" button copies the public 302 URL to the
 * clipboard so operators can drop it into receipts / ads / SMS.
 */
@Component({
  selector: 'app-qr-download',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  template: `
    @if (link(); as l) {
      <div class="rounded-md border border-zinc-200 bg-white p-3">
        <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
          QR code
        </p>
        <div class="flex flex-col items-center gap-2">
          <img
            [src]="pngUrl()"
            [alt]="'QR for ' + l.label"
            class="h-48 w-48 rounded-md border border-zinc-200 bg-white"
          />
          <p class="text-center text-[11px] text-zinc-500">
            Scan with any phone camera — opens WhatsApp with the
            prefilled message ready to send.
          </p>
        </div>

        <div class="mt-3 grid grid-cols-2 gap-2 text-xs">
          <a
            [href]="pngUrl()"
            [download]="'qr-' + l.code + '.png'"
            target="_blank"
            rel="noopener"
            class="inline-flex items-center justify-center gap-1.5 rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 font-medium text-zinc-700 hover:bg-zinc-50"
          >
            <lucide-icon name="download" class="h-3.5 w-3.5" />
            PNG 512px
          </a>
          <a
            [href]="pngLargeUrl()"
            [download]="'qr-' + l.code + '-1024.png'"
            target="_blank"
            rel="noopener"
            class="inline-flex items-center justify-center gap-1.5 rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 font-medium text-zinc-700 hover:bg-zinc-50"
          >
            <lucide-icon name="download" class="h-3.5 w-3.5" />
            PNG 1024px
          </a>
          <a
            [href]="svgUrl()"
            [download]="'qr-' + l.code + '.svg'"
            target="_blank"
            rel="noopener"
            class="col-span-2 inline-flex items-center justify-center gap-1.5 rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 font-medium text-zinc-700 hover:bg-zinc-50"
          >
            <lucide-icon name="download" class="h-3.5 w-3.5" />
            SVG (vector)
          </a>
        </div>

        <div class="mt-3 rounded-md border border-zinc-200 bg-zinc-50 p-2 text-xs">
          <p class="mb-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
            Public URL (also the QR target)
          </p>
          <div class="flex items-center gap-1">
            <code class="flex-1 truncate text-[11px] text-zinc-700">
              {{ publicUrl() }}
            </code>
            <button
              type="button"
              (click)="copyUrl()"
              class="rounded border border-zinc-300 bg-white px-2 py-0.5 text-[11px] text-zinc-700 hover:bg-zinc-100"
            >
              {{ copied() ? 'Copied!' : 'Copy' }}
            </button>
          </div>
        </div>
      </div>
    }
  `,
})
export class QrDownloadComponent {
  private readonly api = inject(QuickLinksService);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);

  readonly link = input.required<QuickLink | null>();

  protected readonly copied = signal<boolean>(false);

  protected readonly pngUrl = computed(() => {
    const l = this.link();
    return l ? this.api.qrPngUrl(l.id, 512) : '';
  });

  protected readonly pngLargeUrl = computed(() => {
    const l = this.link();
    return l ? this.api.qrPngUrl(l.id, 1024) : '';
  });

  protected readonly svgUrl = computed(() => {
    const l = this.link();
    return l ? this.api.qrSvgUrl(l.id) : '';
  });

  protected readonly publicUrl = computed(() => {
    const l = this.link();
    return l ? this.api.publicUrl(l.code) : '';
  });

  protected copyUrl(): void {
    const url = this.publicUrl();
    if (!url) return;
    navigator.clipboard?.writeText(url).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    });
  }
}
