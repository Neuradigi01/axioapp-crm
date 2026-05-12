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

  protected toneClass(tone: ToastTone): string {
    switch (tone) {
      case 'success':
        return 'border-emerald-200 bg-emerald-50';
      case 'error':
        return 'border-red-200 bg-red-50';
      default:
        return 'border-zinc-200 bg-white';
    }
  }

  protected toneIcon(tone: ToastTone): string {
    switch (tone) {
      case 'success':
        return 'check';
      case 'error':
        return 'x';
      default:
        return 'bell';
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
