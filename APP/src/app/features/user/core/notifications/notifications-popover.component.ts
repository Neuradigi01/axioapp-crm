import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';

import { RelativeTimePipe } from '../activities/relative-time.pipe';
import { Notification, NotificationsApiService } from './notifications-api.service';

/**
 * Header bell popover. Pulls the recent 20 the first time it opens
 * (cached on the service singleton thereafter so re-opens are
 * instant). Click a row → mark-read + navigate to `payload.deeplink`
 * when present.
 */
@Component({
  selector: 'app-notifications-popover',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RelativeTimePipe],
  templateUrl: './notifications-popover.component.html',
})
export class NotificationsPopoverComponent {
  private readonly api = inject(NotificationsApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  readonly open = input<boolean>(false);
  readonly closeRequested = output<void>();

  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly hasFetched = signal(false);

  /** Reflect the singleton service's state. */
  protected readonly items = this.api.recent;
  protected readonly unreadCount = this.api.unreadCount;

  protected readonly hasUnread = computed(() => this.unreadCount() > 0);

  constructor() {
    effect(() => {
      // Lazy fetch — only on first open.
      if (this.open() && !this.hasFetched()) {
        this.fetch();
      }
    });
  }

  protected onItemClick(n: Notification): void {
    if (n.read_at === null) {
      this.api
        .markRead(n.id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          error: () => {
            /* swallow — UI already optimistically updated by the service */
          },
        });
    }
    const deeplink = this.deeplink(n);
    if (deeplink) this.router.navigateByUrl(deeplink);
    this.closeRequested.emit();
  }

  protected onMarkAllRead(): void {
    this.api
      .markAllRead()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe();
  }

  private fetch(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list(20)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.loading.set(false);
          this.hasFetched.set(true);
        },
        error: () => {
          this.loading.set(false);
          this.loadError.set('Could not load notifications.');
        },
      });
  }

  private deeplink(n: Notification): string | null {
    const dl = (n.payload as { deeplink?: unknown }).deeplink;
    return typeof dl === 'string' ? dl : null;
  }
}
