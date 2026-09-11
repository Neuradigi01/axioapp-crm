import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  inject,
  input,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  CustomEvent,
  CustomEventsApiService,
} from '../settings/custom-events/custom-events-api.service';

/**
 * "Log event" dropdown for the contact detail page.
 *
 * On click, opens a menu of the org's live custom events. Clicking a
 * menu item POSTs `/custom-events/{id}/fire` with the current contact —
 * the backend logs the occurrence + publishes on the bus so any
 * workflow subscribed to `custom.<event_key>` runs.
 *
 * Events are lazy-loaded on first open so the dropdown doesn't pay
 * an extra round-trip on every contact-page render.
 */
@Component({
  selector: 'app-log-event-button',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, RouterLink],
  template: `
    <div class="relative inline-block">
      <button
        type="button"
        (click)="toggleOpen()"
        class="inline-flex items-center gap-1.5 rounded-lg border border-subtle bg-surface px-3 py-1.5 text-sm font-medium text-default hover:bg-surface-2"
        [attr.aria-expanded]="open()"
      >
        <lucide-icon name="zap" class="h-4 w-4" />
        Log event
        <lucide-icon name="chevron-down" class="h-3.5 w-3.5" />
      </button>

      @if (open()) {
        <div
          class="absolute right-0 z-30 mt-1 w-72 rounded-lg border border-subtle bg-surface shadow-lg ring-1 ring-black/5"
        >
          @if (loading()) {
            <div class="flex items-center gap-2 p-3 text-sm text-muted">
              <lucide-icon name="loader-2" class="h-4 w-4 animate-spin" />
              Loading events…
            </div>
          } @else if (loadError()) {
            <div class="p-3 text-sm text-amber-400">{{ loadError() }}</div>
          } @else if (events().length === 0) {
            <div class="p-4 text-center">
              <p class="text-xs text-muted">No custom events yet.</p>
              <a
                routerLink="/user/settings/custom-events"
                (click)="close()"
                class="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:underline"
              >
                <lucide-icon name="plus" class="h-3.5 w-3.5" />
                Create your first event
              </a>
            </div>
          } @else {
            <div class="max-h-72 overflow-y-auto py-1">
              @for (evt of events(); track evt.id) {
                <button
                  type="button"
                  (click)="onFire(evt)"
                  [disabled]="firingId() === evt.id"
                  class="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left text-sm hover:bg-surface-2 disabled:opacity-60"
                >
                  <span class="flex w-full items-center justify-between gap-2">
                    <span class="font-medium text-default">{{ evt.name }}</span>
                    @if (firingId() === evt.id) {
                      <lucide-icon name="loader-2" class="h-3.5 w-3.5 animate-spin" />
                    }
                  </span>
                  <span class="font-mono text-[11px] text-muted"> custom.{{ evt.event_key }} </span>
                </button>
              }
            </div>
            <div class="border-t border-subtle p-2">
              <a
                routerLink="/user/settings/custom-events"
                (click)="close()"
                class="flex items-center justify-center gap-1 rounded-md px-2 py-1 text-xs text-muted hover:bg-surface-2 hover:text-default"
              >
                <lucide-icon name="settings" class="h-3.5 w-3.5" />
                Manage custom events
              </a>
            </div>
          }
        </div>
      }

      @if (toast(); as t) {
        <div
          class="absolute right-0 top-full z-40 mt-2 min-w-[240px] rounded-md border px-3 py-2 text-sm shadow-md"
          [class.border-emerald-500\\/20]="t.kind === 'ok'"
          [class.bg-emerald-500\\/10]="t.kind === 'ok'"
          [class.text-emerald-500]="t.kind === 'ok'"
          [class.border-red-500\\/20]="t.kind === 'error'"
          [class.bg-red-500\\/10]="t.kind === 'error'"
          [class.text-red-500]="t.kind === 'error'"
        >
          {{ t.message }}
        </div>
      }
    </div>
  `,
})
export class LogEventButtonComponent {
  readonly contactId = input.required<string>();

  private readonly api = inject(CustomEventsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly elementRef = inject(ElementRef);

  protected readonly open = signal(false);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly events = signal<CustomEvent[]>([]);
  protected readonly firingId = signal<string | null>(null);
  protected readonly toast = signal<{ kind: 'ok' | 'error'; message: string } | null>(null);

  private loadedOnce = false;
  private toastTimer: ReturnType<typeof setTimeout> | null = null;

  protected toggleOpen(): void {
    const next = !this.open();
    this.open.set(next);
    if (next && !this.loadedOnce) {
      this.loadOnce();
    }
  }

  protected close(): void {
    this.open.set(false);
  }

  @HostListener('document:click', ['$event'])
  private onDocumentClick(evt: MouseEvent): void {
    if (!this.open()) return;
    const target = evt.target as Node | null;
    if (target && !this.elementRef.nativeElement.contains(target)) {
      this.close();
    }
  }

  private loadOnce(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.events.set(rows);
          this.loading.set(false);
          this.loadedOnce = true;
        },
        error: (err: HttpErrorResponse) => {
          const msg = extractApiError(err) ?? 'Could not load custom events.';
          if (err.status === 403) {
            this.loadError.set('You need permission to view custom events.');
          } else {
            this.loadError.set(msg);
          }
          this.loading.set(false);
        },
      });
  }

  protected onFire(evt: CustomEvent): void {
    if (this.firingId() !== null) return;
    this.firingId.set(evt.id);
    this.api
      .fire(evt.id, { contact_id: this.contactId() })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.firingId.set(null);
          this.close();
          this.showToast('ok', `Logged “${evt.name}” — workflows notified.`);
        },
        error: (err: HttpErrorResponse) => {
          this.firingId.set(null);
          const msg = extractApiError(err) ?? 'Could not fire event.';
          this.showToast('error', msg);
        },
      });
  }

  private showToast(kind: 'ok' | 'error', message: string): void {
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toast.set({ kind, message });
    this.toastTimer = setTimeout(() => {
      this.toast.set(null);
      this.toastTimer = null;
    }, 3500);
  }
}
