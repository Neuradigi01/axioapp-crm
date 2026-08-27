import { Injectable, inject } from '@angular/core';
import { MatSnackBar, MatSnackBarConfig } from '@angular/material/snack-bar';

import { ToastData, ToastPanelComponent, ToastVariant } from './toast-panel.component';

/** Options a caller can override on a per-toast basis. Defaults live
 *  inside `ToastService.show`. `subtitle` is the only new field
 *  beyond MatSnackBar's built-ins — the rest just re-route the
 *  underlying `MatSnackBarConfig`. */
export interface ToastOptions {
  /** Optional secondary line under the title. Kept short — the panel
   *  renders it in a lighter weight and 12 px font. */
  subtitle?: string | null;
  /** Auto-dismiss delay in ms. `0` = no auto-dismiss (operator must
   *  click the close X). Defaults per variant: success 3 s, info 3 s,
   *  warn 5 s, error 6 s. */
  durationMs?: number;
}

/** Per-variant default lifetimes. Errors linger the longest so the
 *  operator has time to read the failure reason before it slides out. */
const DEFAULT_DURATION: Record<ToastVariant, number> = {
  success: 3000,
  info: 3000,
  warn: 5000,
  error: 6000,
};

/**
 * App-wide toast helper. Wraps `MatSnackBar.openFromComponent` so
 * every visual detail (icon, colour, layout, close button) is
 * controlled by `ToastPanelComponent` — callers just say "success"
 * / "error" and hand over the message.
 *
 * Callers should NOT talk to `MatSnackBar` directly for user-facing
 * toasts; use this service so the styling stays consistent. The one
 * remaining direct-use path is `styles.scss`'s generic
 * `.mat-mdc-snack-bar-container` override, which is a defensive
 * fallback for any residual `MatSnackBar.open('...')` call.
 */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly snackBar = inject(MatSnackBar);

  success(title: string, opts: ToastOptions = {}): void {
    this.show('success', title, opts);
  }

  info(title: string, opts: ToastOptions = {}): void {
    this.show('info', title, opts);
  }

  warn(title: string, opts: ToastOptions = {}): void {
    this.show('warn', title, opts);
  }

  error(title: string, opts: ToastOptions = {}): void {
    this.show('error', title, opts);
  }

  private show(variant: ToastVariant, title: string, opts: ToastOptions): void {
    const data: ToastData = {
      variant,
      title,
      subtitle: opts.subtitle ?? null,
    };
    const config: MatSnackBarConfig<ToastData> = {
      data,
      // `panelClass` on the snackbar-container wrapper — the CSS in
      // `styles.scss` uses `.toast-panel-wrapper` to strip Material's
      // MDC surface (rounded corners / shadow / padding) that would
      // otherwise fight our custom panel.
      panelClass: ['toast-panel-wrapper'],
      duration: opts.durationMs ?? DEFAULT_DURATION[variant],
      horizontalPosition: 'right',
      verticalPosition: 'top',
    };
    this.snackBar.openFromComponent(ToastPanelComponent, config);
  }
}
