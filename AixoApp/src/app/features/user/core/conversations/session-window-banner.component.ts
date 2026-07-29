import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  OnDestroy,
  OnInit,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { WhatsAppSessionState } from './conversations-api.service';

/**
 * 24-hour session window banner
 * (whatsapp-platform-upgrade Step 15).
 *
 * Green strip when in-session ("Free session — expires in Xh Ym"),
 * yellow strip when out-of-session ("24-hr session expired. Only
 * approved templates can be sent.") with a `[Pick template]` CTA
 * that bubbles via `(pickTemplate)`.
 *
 * State auto-refreshes every 60 seconds so the countdown ticks
 * without a server round-trip. Recomputed on visibility-change so
 * a tab returning from background snaps back to accurate time.
 *
 * Renders nothing when `state` is null — non-WhatsApp conversations
 * skip the banner entirely.
 */
@Component({
  selector: 'app-session-window-banner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  template: `
    @if (display(); as d) {
      <div
        [class]="
          'flex items-center justify-between gap-2 border-b px-4 py-2 text-xs ' +
          (d.inSession
            ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
            : 'border-amber-200 bg-amber-50 text-amber-900')
        "
      >
        <div class="flex items-center gap-2">
          @if (d.inSession) {
            <lucide-icon name="check-circle-2" size="14" />
            <span>
              <span class="font-semibold">Free session</span>
              · expires in {{ d.remaining }}
            </span>
          } @else {
            <lucide-icon name="alert-triangle" size="14" />
            <span>
              <span class="font-semibold">24-hr session expired.</span>
              Only approved templates can be sent.
            </span>
          }
        </div>
        @if (!d.inSession) {
          <button
            type="button"
            (click)="pickTemplate.emit()"
            class="rounded-md border border-amber-300 bg-surface px-2.5 py-1 text-[11px] font-semibold text-amber-800 hover:bg-amber-100"
          >
            Pick template
          </button>
        }
      </div>
    }
  `,
})
export class SessionWindowBannerComponent implements OnInit, OnDestroy {
  private readonly destroyRef = inject(DestroyRef);

  @Input() state: WhatsAppSessionState | null = null;
  @Output() readonly pickTemplate = new EventEmitter<void>();

  /** Tick signal — flips every minute so the `display` computed
   *  re-evaluates the countdown without a server round-trip. */
  private readonly tick = signal<number>(0);

  private intervalHandle: ReturnType<typeof setInterval> | null = null;
  private readonly visibilityHandler = () => this.tick.update((v) => v + 1);

  protected readonly display = computed<{ inSession: boolean; remaining: string } | null>(() => {
    // Consume the tick signal so this computed re-runs on each minute.
    this.tick();
    const s = this.state;
    if (!s) return null;
    if (!s.in_session || !s.expires_at) {
      return { inSession: false, remaining: '' };
    }
    const now = Date.now();
    const expires = new Date(s.expires_at).getTime();
    const deltaMs = expires - now;
    if (deltaMs <= 0) {
      // Crossed the boundary while the banner was visible — flip
      // optimistically without waiting for the next poll.
      return { inSession: false, remaining: '' };
    }
    const totalMinutes = Math.floor(deltaMs / 60000);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    const remaining = hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
    return { inSession: true, remaining };
  });

  ngOnInit(): void {
    // Refresh every 60s while mounted.
    this.intervalHandle = setInterval(() => this.tick.update((v) => v + 1), 60_000);
    // Recompute on tab-visibility change so a backgrounded tab snaps
    // back to current state when re-focused.
    document.addEventListener('visibilitychange', this.visibilityHandler);
    this.destroyRef.onDestroy(() => this.ngOnDestroy());
  }

  ngOnDestroy(): void {
    if (this.intervalHandle !== null) {
      clearInterval(this.intervalHandle);
      this.intervalHandle = null;
    }
    document.removeEventListener('visibilitychange', this.visibilityHandler);
  }
}
