import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { Router } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { Toast, ToastHostService, ToastTone } from './toast-host.service';

/**
 * Bottom-right toast stack. Rendered once at the app shell level via
 * `<app-toast-host>`; the toast queue lives on `ToastHostService`.
 *
 * Click on a toast with `href` navigates and dismisses; clicking the
 * close-x dismisses without navigating.
 */
@Component({
  selector: 'app-toast-host',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './toast-host.component.html',
})
export class ToastHostComponent {
  private readonly service = inject(ToastHostService);
  private readonly router = inject(Router);

  readonly toasts = this.service.toasts;

  protected toneIcon(tone: ToastTone): string {
    switch (tone) {
      case 'success':
        return 'check-circle-2';
      case 'error':
        return 'x-circle';
      default:
        return 'bell';
    }
  }

  protected toneIconClass(tone: ToastTone): string {
    switch (tone) {
      case 'success':
        return 'text-emerald-400';
      case 'error':
        return 'text-red-400';
      default:
        return 'text-accent';
    }
  }

  protected onClick(t: Toast): void {
    if (t.href) {
      this.router.navigateByUrl(t.href);
    }
    this.service.dismiss(t.id);
  }

  protected onClose(event: Event, id: number): void {
    event.stopPropagation();
    this.service.dismiss(id);
  }
}
