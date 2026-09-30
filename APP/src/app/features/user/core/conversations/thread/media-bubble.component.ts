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
import { LucideAngularModule } from 'lucide-angular';

import { environment } from '../../../../../../environments/environment';

/** WhatsApp media attachment as persisted on a message. Inbound Cloud
 *  API rows carry Meta's `id`; ones we uploaded carry `media_id`;
 *  WhatsApp Web rows carry `provider_message_id`. The backend proxy
 *  resolves whichever is present. */
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

/**
 * Renders one WhatsApp media attachment inside a chat bubble.
 *
 *   image / sticker  → thumbnail, loaded when scrolled into view; click
 *                      (images) opens a full-screen lightbox
 *   audio            → native player, loaded when scrolled into view
 *   video            → poster button; bytes load only on click (videos
 *                      can be 16 MB, never auto-download a thread's worth)
 *   document         → file chip; click downloads
 *
 * Bytes come from `GET /conversations/{id}/messages/{mid}/media/{index}`
 * through HttpClient (so the auth interceptor attaches the JWT) and are
 * shown via an object URL that is revoked on destroy.
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
              (click)="lightboxOpen.set(true)"
              aria-label="Open image"
            >
              <img
                [src]="objectUrl()"
                [alt]="att.caption || 'Image'"
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
          <button
            type="button"
            (click)="download()"
            [disabled]="state() === 'loading'"
            [title]="state() === 'unavailable' ? unavailableText : 'Download'"
            class="inline-flex max-w-full items-center gap-2 rounded-md ring-1 ring-black/10 bg-black/5 px-2.5 py-1.5 text-left text-xs transition hover:bg-black/10 disabled:opacity-60"
          >
            @if (state() === 'loading') {
              <lucide-icon name="loader-2" class="h-4 w-4 shrink-0 animate-spin" />
            } @else {
              <lucide-icon name="file-text" class="h-4 w-4 shrink-0" />
            }
            <span class="min-w-0">
              <span class="block max-w-[220px] truncate font-medium">{{ fileName() }}</span>
              <span class="block text-[10px] opacity-70">
                @if (state() === 'unavailable') {
                  {{ unavailableText }}
                } @else {
                  {{ sizeLabel() || 'Document' }} · Download
                }
              </span>
            </span>
          </button>
        }
      }
    }

    @if (lightboxOpen() && objectUrl()) {
      <div
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4"
        role="dialog"
        aria-modal="true"
        aria-label="Image preview"
        (click)="lightboxOpen.set(false)"
      >
        <img
          [src]="objectUrl()"
          [alt]="attachment().caption || 'Image'"
          class="max-h-full max-w-full rounded-md object-contain"
          (click)="$event.stopPropagation()"
        />
        <div class="absolute right-4 top-4 flex gap-2">
          <button
            type="button"
            (click)="download(); $event.stopPropagation()"
            class="rounded-full bg-white/10 p-2 text-white transition hover:bg-white/20"
            aria-label="Download image"
          >
            <lucide-icon name="download" class="h-5 w-5" />
          </button>
          <button
            type="button"
            (click)="lightboxOpen.set(false)"
            class="rounded-full bg-white/10 p-2 text-white transition hover:bg-white/20"
            aria-label="Close preview"
          >
            <lucide-icon name="x" class="h-5 w-5" />
          </button>
        </div>
      </div>
    }
  `,
})
export class MediaBubbleComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly host = inject(ElementRef<HTMLElement>);

  readonly conversationId = input.required<string>();
  readonly messageId = input.required<string>();
  /** Position of this attachment in the message's `attachments[]`. */
  readonly index = input.required<number>();
  readonly attachment = input.required<MediaAttachment>();

  protected readonly state = signal<LoadState>('idle');
  protected readonly objectUrl = signal<string | null>(null);
  protected readonly lightboxOpen = signal(false);
  protected readonly unavailableText = 'Media no longer available';

  protected readonly label = computed(() => {
    const t = this.attachment().type;
    return t === 'image' ? 'photo' : t === 'audio' ? 'voice note' : t;
  });

  protected readonly fileName = computed(() => {
    const a = this.attachment();
    return a.filename || (a.type === 'document' ? 'Document' : this.label());
  });

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
    if (this.lightboxOpen()) this.lightboxOpen.set(false);
  }

  protected load(onReady?: (url: string) => void): void {
    const existing = this.objectUrl();
    if (existing) {
      onReady?.(existing);
      return;
    }
    if (this.state() === 'loading') return;
    this.state.set('loading');
    const url =
      `${environment.apiBaseUrl}/conversations/${this.conversationId()}` +
      `/messages/${this.messageId()}/media/${this.index()}`;
    this.http
      .get(url, { responseType: 'blob' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          const objectUrl = URL.createObjectURL(blob);
          this.objectUrl.set(objectUrl);
          this.state.set('ready');
          onReady?.(objectUrl);
        },
        error: (_err: HttpErrorResponse) => this.state.set('unavailable'),
      });
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
