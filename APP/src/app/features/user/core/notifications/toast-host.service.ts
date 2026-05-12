import { Injectable, signal } from '@angular/core';

/**
 * Global toast queue. `<app-toast-host>` lives once at the app shell
 * level and renders this signal — any component / service can
 * `inject(ToastHostService).push({...})` to surface a transient
 * message.
 *
 * Toasts auto-dismiss after `durationMs` (default 5 s); callers can
 * also `dismiss(id)` early. Each toast has a unique id so the
 * template's `track` key is stable.
 */
export type ToastTone = 'info' | 'success' | 'error';

export interface Toast {
  id: number;
  title: string;
  body?: string;
  tone: ToastTone;
  /** Optional click target — opens via the host when set. */
  href?: string;
  /** Milliseconds before auto-dismiss. Default 5 s. */
  durationMs: number;
}

@Injectable({ providedIn: 'root' })
export class ToastHostService {
  private readonly _toasts = signal<Toast[]>([]);
  readonly toasts = this._toasts.asReadonly();

  private nextId = 1;
  private readonly timers = new Map<number, ReturnType<typeof setTimeout>>();

  push(input: Partial<Toast> & { title: string }): number {
    const id = this.nextId++;
    const toast: Toast = {
      id,
      title: input.title,
      body: input.body,
      tone: input.tone ?? 'info',
      href: input.href,
      durationMs: input.durationMs ?? 5_000,
    };
    this._toasts.update((rows) => [...rows, toast]);
    if (toast.durationMs > 0) {
      const handle = setTimeout(() => this.dismiss(id), toast.durationMs);
      this.timers.set(id, handle);
    }
    return id;
  }

  dismiss(id: number): void {
    const handle = this.timers.get(id);
    if (handle !== undefined) {
      clearTimeout(handle);
      this.timers.delete(id);
    }
    this._toasts.update((rows) => rows.filter((t) => t.id !== id));
  }

  clear(): void {
    for (const handle of this.timers.values()) clearTimeout(handle);
    this.timers.clear();
    this._toasts.set([]);
  }
}
