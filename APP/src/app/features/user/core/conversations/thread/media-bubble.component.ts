import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  OnInit,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { LucideAngularModule } from 'lucide-angular';

import { environment } from '../../../../../../environments/environment';

/** A media attachment on a message. WhatsApp rows: inbound Cloud API
 *  carries Meta's `id`, ones we uploaded carry `media_id`, WhatsApp Web
 *  carries `provider_message_id` — the backend proxy resolves whichever
 *  is present. Email files are passed with an explicit `src`. */
export interface MediaAttachment {
  type: 'image' | 'video' | 'audio' | 'document' | 'sticker';
  mime_type?: string | null;
  filename?: string | null;
  caption?: string | null;
  size_bytes?: number | null;
  file_size?: number | null;
  /** Optimistic outbound row still uploading (no provider reference yet). */
  uploading?: boolean;
}

type LoadState = 'idle' | 'loading' | 'ready' | 'unavailable';

/** MIME types we let the browser render in-page (from a blob URL on our
 *  origin). Everything else — SVG, HTML, unknown — is download-only. */
function isViewableMime(mime: string): boolean {
  if (mime === 'image/svg+xml') return false;
  return (
    mime.startsWith('image/') ||
    mime.startsWith('video/') ||
    mime.startsWith('audio/') ||
    mime === 'application/pdf'
  );
}

/**
 * Renders one media attachment inside a chat bubble.
 *
 *   image / sticker  → thumbnail, loaded when scrolled into view; click
 *                      (images) opens a full-screen viewer
 *   audio            → native player, loaded when scrolled into view
 *   video            → poster button; bytes load only on click (videos
 *                      can be 16 MB, never auto-download a thread's worth)
 *   document         → file chip with Download, plus View for PDFs
 *                      (opens the in-page viewer)
 *
 * Bytes are fetched through HttpClient (so the auth interceptor attaches
 * the JWT) — from the WhatsApp media proxy
 * `GET /conversations/{id}/messages/{mid}/media/{index}`, or from `src`
 * when given (email attachments). They're shown via an object URL
 * re-typed with the attachment's MIME and revoked on destroy.
 */
@Component({
  selector: 'app-media-bubble',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    @let att = attachment();
    @if (att.uploading) {
      <div class="flex items-center gap-2 text-xs opacity-80">
        <lucide-icon name="loader-2" class="h-3.5 w-3.5 animate-spin" />
        Uploading {{ label() }}…
      </div>
    } @else {
      @switch (att.type) {
        @case ('image') {
          @if (state() === 'ready') {
            <button
              type="button"
              class="block overflow-hidden rounded-lg"
              (click)="viewerOpen.set(true)"
              aria-label="Open image"
            >
              <img
                [src]="objectUrl()"
                [alt]="att.caption || att.filename || 'Image'"
                class="max-h-72 w-auto max-w-full object-cover"
              />
            </button>
          } @else {
            <div
              class="flex h-40 w-56 max-w-full items-center justify-center rounded-lg bg-black/10"
            >
              @if (state() === 'unavailable') {
                <span class="px-3 text-center text-[11px] opacity-80">{{ unavailableText }}</span>
              } @else {
                <lucide-icon name="image" class="h-6 w-6 animate-pulse opacity-60" />
              }
            </div>
          }
        }
        @case ('sticker') {
          @if (state() === 'ready') {
            <img [src]="objectUrl()" alt="Sticker" class="h-32 w-32 object-contain" />
          } @else {
            <div class="flex h-32 w-32 items-center justify-center rounded-lg bg-black/10">
              @if (state() === 'unavailable') {
                <span class="px-2 text-center text-[10px] opacity-80">Sticker</span>
              } @else {
                <lucide-icon name="smile" class="h-6 w-6 animate-pulse opacity-60" />
              }
            </div>
          }
        }
        @case ('audio') {
          @if (state() === 'ready') {
            <audio
              [src]="objectUrl()"
              controls
              preload="metadata"
              class="h-10 w-64 max-w-full"
            ></audio>
          } @else if (state() === 'unavailable') {
            <p class="text-[11px] opacity-80">{{ unavailableText }}</p>
          } @else {
            <div class="flex h-10 w-64 max-w-full items-center gap-2 text-xs opacity-80">
              <lucide-icon name="music" class="h-4 w-4 animate-pulse" />
              Loading voice note…
            </div>
          }
        }
        @case ('video') {
          @if (state() === 'ready') {
            <video
              [src]="objectUrl()"
              controls
              autoplay
              class="max-h-72 w-auto max-w-full rounded-lg bg-black"
            ></video>
          } @else if (state() === 'unavailable') {
            <p class="text-[11px] opacity-80">{{ unavailableText }}</p>
          } @else {
            <button
              type="button"
              (click)="load()"
              [disabled]="state() === 'loading'"
              class="flex h-36 w-56 max-w-full items-center justify-center rounded-lg bg-black/70 text-white transition hover:bg-black/60"
              aria-label="Play video"
            >
              @if (state() === 'loading') {
                <lucide-icon name="loader-2" class="h-7 w-7 animate-spin" />
              } @else {
                <lucide-icon name="play" class="h-8 w-8" />
              }
            </button>
          }
        }
        @default {
          <div
            class="inline-flex max-w-full items-center gap-2 rounded-md bg-black/5 px-2.5 py-1.5 text-xs ring-1 ring-black/10"
          >
            @if (state() === 'loading') {
              <lucide-icon name="loader-2" class="h-4 w-4 shrink-0 animate-spin" />
            } @else {
              <lucide-icon name="file-text" class="h-4 w-4 shrink-0" />
            }
            <span class="min-w-0">
              <span class="block max-w-[200px] truncate font-medium">{{ fileName() }}</span>
              <span class="block text-[10px] opacity-70">
                @if (state() === 'unavailable') {
                  {{ unavailableText }}
                } @else {
                  {{ kindLabel() }}{{ sizeLabel() ? ' · ' + sizeLabel() : '' }}
                }
              </span>
            </span>
            @if (state() !== 'unavailable') {
              @if (isPdf()) {
                <button
                  type="button"
                  (click)="openViewer()"
                  [disabled]="state() === 'loading'"
                  class="shrink-0 rounded px-1.5 py-0.5 font-medium underline-offset-2 hover:underline disabled:opacity-60"
                >
                  View
                </button>
              }
              <button
                type="button"
                (click)="download()"
                [disabled]="state() === 'loading'"
                class="shrink-0 rounded p-1 hover:bg-black/10 disabled:opacity-60"
                [attr.aria-label]="'Download ' + fileName()"
                title="Download"
              >
                <lucide-icon name="download" class="h-3.5 w-3.5" />
              </button>
            }
          </div>
        }
      }
    }

    @if (viewerOpen() && objectUrl()) {
      <div
        class="fixed inset-0 z-50 flex flex-col bg-black/85 p-4"
        role="dialog"
        aria-modal="true"
        [attr.aria-label]="fileName()"
        (click)="viewerOpen.set(false)"
      >
        <div class="mb-2 flex items-center justify-between gap-2 text-white">
          <span class="min-w-0 truncate text-sm font-medium">{{ fileName() }}</span>
          <div class="flex shrink-0 gap-2">
            <button
              type="button"
              (click)="download(); $event.stopPropagation()"
              class="rounded-full bg-white/10 p-2 transition hover:bg-white/20"
              aria-label="Download"
            >
              <lucide-icon name="download" class="h-5 w-5" />
            </button>
            <button
              type="button"
              (click)="viewerOpen.set(false)"
              class="rounded-full bg-white/10 p-2 transition hover:bg-white/20"
              aria-label="Close preview"
            >
              <lucide-icon name="x" class="h-5 w-5" />
            </button>
          </div>
        </div>
        <div
          class="flex min-h-0 flex-1 items-center justify-center"
          (click)="$event.stopPropagation()"
        >
          @if (isPdf()) {
            @if (pdfUrl(); as url) {
              <iframe
                [src]="url"
                [title]="fileName()"
                class="h-full w-full max-w-5xl rounded-md bg-white"
              ></iframe>
            }
          } @else {
            <img
              [src]="objectUrl()"
              [alt]="attachment().caption || fileName()"
              class="max-h-full max-w-full rounded-md object-contain"
            />
          }
        </div>
      </div>
    }
  `,
})
export class MediaBubbleComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly sanitizer = inject(DomSanitizer);

  /** WhatsApp proxy addressing — ignored when `src` is set. */
  readonly conversationId = input<string | null>(null);
  readonly messageId = input<string | null>(null);
  /** Position of this attachment in the message's `attachments[]`. */
  readonly index = input<number>(0);
  /** Explicit authenticated URL (email attachment download endpoint). */
  readonly src = input<string | null>(null);
  readonly attachment = input.required<MediaAttachment>();

  protected readonly state = signal<LoadState>('idle');
  protected readonly objectUrl = signal<string | null>(null);
  /** Same object URL, trusted for the PDF <iframe> (resource context).
   *  Only ever a blob: URL we minted from a MIME-checked PDF. */
  protected readonly pdfUrl = signal<SafeResourceUrl | null>(null);
  protected readonly viewerOpen = signal(false);
  protected readonly unavailableText = 'Media no longer available';

  protected readonly mime = computed(() => (this.attachment().mime_type ?? '').toLowerCase());
  protected readonly isPdf = computed(
    () => this.mime() === 'application/pdf' || /\.pdf$/i.test(this.attachment().filename ?? ''),
  );

  protected readonly label = computed(() => {
    const t = this.attachment().type;
    return t === 'image' ? 'photo' : t === 'audio' ? 'voice note' : t;
  });

  protected readonly fileName = computed(() => {
    const a = this.attachment();
    return a.filename || (a.type === 'document' ? 'Document' : this.label());
  });

  protected readonly kindLabel = computed(() => (this.isPdf() ? 'PDF' : 'File'));

  protected readonly sizeLabel = computed(() => {
    const a = this.attachment();
    const bytes = a.size_bytes ?? a.file_size ?? 0;
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  });

  private observer: IntersectionObserver | null = null;

  ngOnInit(): void {
    const type = this.attachment().type;
    // Thumbnails + voice notes load as they scroll into view; video and
    // documents wait for an explicit click.
    if (
      !this.attachment().uploading &&
      (type === 'image' || type === 'sticker' || type === 'audio')
    ) {
      this.observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            this.observer?.disconnect();
            this.observer = null;
            this.load();
          }
        },
        { rootMargin: '200px' },
      );
      this.observer.observe(this.host.nativeElement);
    }
    this.destroyRef.onDestroy(() => {
      this.observer?.disconnect();
      const url = this.objectUrl();
      if (url) URL.revokeObjectURL(url);
    });
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (this.viewerOpen()) this.viewerOpen.set(false);
  }

  private mediaUrl(): string | null {
    const explicit = this.src();
    if (explicit) return explicit;
    const conv = this.conversationId();
    const msg = this.messageId();
    if (!conv || !msg) return null;
    return `${environment.apiBaseUrl}/conversations/${conv}/messages/${msg}/media/${this.index()}`;
  }

  protected load(onReady?: (url: string) => void): void {
    const existing = this.objectUrl();
    if (existing) {
      onReady?.(existing);
      return;
    }
    const url = this.mediaUrl();
    if (!url) {
      this.state.set('unavailable');
      return;
    }
    if (this.state() === 'loading') return;
    this.state.set('loading');
    this.http
      .get(url, { responseType: 'blob' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          // Downloads are served as octet-stream; re-type with the
          // attachment's own MIME so images / PDFs render — but only for
          // the safe, viewable set.
          const mime = this.isPdf() ? 'application/pdf' : this.mime();
          const typed = mime && isViewableMime(mime) ? new Blob([blob], { type: mime }) : blob;
          const objectUrl = URL.createObjectURL(typed);
          this.objectUrl.set(objectUrl);
          if (this.isPdf()) {
            this.pdfUrl.set(this.sanitizer.bypassSecurityTrustResourceUrl(objectUrl));
          }
          this.state.set('ready');
          onReady?.(objectUrl);
        },
        error: (_err: HttpErrorResponse) => this.state.set('unavailable'),
      });
  }

  protected openViewer(): void {
    this.load(() => this.viewerOpen.set(true));
  }

  protected download(): void {
    if (this.state() === 'unavailable') return;
    this.load((objectUrl) => {
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = this.fileName();
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    });
  }
}
