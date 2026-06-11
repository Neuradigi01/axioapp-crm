/**
 * Disconnect-confirmation modal.
 *
 * Renders a Tailwind backdrop + centred card with a clear list of
 * what happens on disconnect:
 *   - sync stops immediately (no new messages flow into the inbox),
 *   - send-from-CRM stops (sequences using this mailbox skip),
 *   - existing conversation history is retained (no destructive
 *     archival — operators can audit the rep's past sends).
 *
 * Parent owns the open/close signal and the target account; this
 * component is presentational. Emits `confirmed` on the primary CTA
 * and `cancelled` on the secondary / backdrop click.
 */
import {
  ChangeDetectionStrategy,
  Component,
  input,
  output,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { EmailAccount } from '../../services/email-accounts-api.service';


@Component({
  selector: 'app-disconnect-confirm-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './disconnect-confirm-dialog.component.html',
})
export class DisconnectConfirmDialogComponent {
  readonly account = input.required<EmailAccount>();
  readonly disconnecting = input<boolean>(false);

  readonly confirmed = output<void>();
  readonly cancelled = output<void>();

  onBackdropClick(event: MouseEvent): void {
    if (event.target === event.currentTarget && !this.disconnecting()) {
      this.cancelled.emit();
    }
  }
}
