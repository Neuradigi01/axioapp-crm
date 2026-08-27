import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MAT_SNACK_BAR_DATA, MatSnackBarRef } from '@angular/material/snack-bar';
import { LucideAngularModule } from 'lucide-angular';

/** Variant → colour + icon mapping. Kept as a plain string literal
 *  union so the service's typed `.success() / .error()` methods trap
 *  bad callers at compile time. */
export type ToastVariant = 'success' | 'info' | 'warn' | 'error';

/** Data injected by `MatSnackBar.openFromComponent` — the service
 *  builds this object; components should never construct it directly. */
export interface ToastData {
  variant: ToastVariant;
  title: string;
  /** Optional secondary line rendered under the title in a lighter
   *  weight. Use it for details like "Retry in 30 s." — keep the
   *  first line as the action outcome so a glance is enough. */
  subtitle?: string | null;
}

/** Lucide icon name per variant. Every icon here is registered in
 *  ``app.config.ts``; adding a new variant means adding its icon to
 *  that registry too or the toast will render blank + break click
 *  handlers further down the DOM (Lucide's throw-mid-render bug). */
const VARIANT_ICON: Record<ToastVariant, string> = {
  success: 'check-circle-2',
  info: 'info',
  warn: 'alert-triangle',
  error: 'x-circle',
};

/**
 * Toast panel rendered inside every `MatSnackBar` call from
 * `ToastService`. Design: left status icon in a coloured pill,
 * bold title, optional secondary line, small `×` close button on
 * the right — matches Vercel / Linear / Sonner conventions.
 *
 * All visual styling (background, border, icon colour) is CSS-var
 * driven and lives in ``styles.scss`` under the `.toast` +
 * `.toast-<variant>` selectors — the component template only
 * carries structural markup so theme swaps flow through the same
 * design-token pipeline as the rest of the app.
 */
@Component({
  selector: 'app-toast-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    <div class="toast-icon">
      <lucide-icon [name]="iconName" class="h-4 w-4" aria-hidden="true" />
    </div>
    <div class="toast-body">
      <p class="toast-title">{{ data.title }}</p>
      @if (data.subtitle) {
        <p class="toast-subtitle">{{ data.subtitle }}</p>
      }
    </div>
    <button type="button" class="toast-close" aria-label="Dismiss notification" (click)="dismiss()">
      <lucide-icon name="x" class="h-3.5 w-3.5" aria-hidden="true" />
    </button>
  `,
  host: {
    class: 'toast',
    '[class.toast-success]': "data.variant === 'success'",
    '[class.toast-info]': "data.variant === 'info'",
    '[class.toast-warn]': "data.variant === 'warn'",
    '[class.toast-error]': "data.variant === 'error'",
    role: 'status',
    'aria-live': 'polite',
  },
})
export class ToastPanelComponent {
  protected readonly data = inject<ToastData>(MAT_SNACK_BAR_DATA);
  private readonly ref = inject<MatSnackBarRef<ToastPanelComponent>>(MatSnackBarRef);

  protected get iconName(): string {
    return VARIANT_ICON[this.data.variant];
  }

  protected dismiss(): void {
    this.ref.dismiss();
  }
}
