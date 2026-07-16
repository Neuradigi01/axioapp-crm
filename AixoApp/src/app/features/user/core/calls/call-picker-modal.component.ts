import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

/**
 * Modal that replaces the browser's ugly "Open Pick an app?" prompt
 * when a user clicks Call on the Phone Book. Shows a clean list of
 * free options — WhatsApp, native dialer / Phone Link, and Copy —
 * with per-option labels that make the cost + delivery mechanism
 * clear.
 *
 * Emits `picked` with the option the user chose so the caller can
 * open the LogCallModal afterwards. Emits `close` when the user
 * dismisses without picking.
 *
 * WhatsApp path: opens ``https://wa.me/<digits>`` in a new tab. That
 * lands on the contact's WhatsApp chat; the user then clicks the
 * voice-call icon in WhatsApp for the actual free VoIP call. WhatsApp
 * has no public URL scheme to initiate a call directly.
 *
 * Native dialer path: fires ``tel:<phone>`` — same as the previous
 * default behaviour. If the OS has a default handler configured
 * (Phone Link, Skype, WhatsApp Desktop, softphone), the call is
 * placed via that. First-time users get the Windows picker exactly
 * once; after "Always allow" it goes straight through.
 *
 * Copy path: writes to the clipboard so the user can paste into any
 * dialer (desk phone, third-party app, etc.).
 */
export type CallOption = 'whatsapp' | 'tel' | 'copy';

@Component({
  selector: 'app-call-picker-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './call-picker-modal.component.html',
})
export class CallPickerModalComponent {
  @Input({ required: true }) contactName = '';
  @Input({ required: true }) phone = '';

  @Output() readonly picked = new EventEmitter<CallOption>();
  @Output() readonly close = new EventEmitter<void>();

  /** Transient state — flips to true right after Copy so the button
   *  briefly reads "Copied ✓" instead of "Copy Number". */
  protected readonly copied = signal(false);

  protected onWhatsApp(): void {
    const digits = this.digitsOnly(this.phone);
    if (digits) {
      window.open(`https://wa.me/${digits}`, '_blank', 'noopener');
    }
    this.picked.emit('whatsapp');
  }

  protected onTel(): void {
    if (this.phone) {
      window.location.href = `tel:${this.phone}`;
    }
    this.picked.emit('tel');
  }

  protected async onCopy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(this.phone);
      this.copied.set(true);
      // Give the user a beat to see the "Copied ✓" feedback before
      // the modal closes.
      setTimeout(() => this.picked.emit('copy'), 600);
    } catch {
      // Clipboard API may fail in some browsers — fall through with
      // the emit so the log modal still opens.
      this.picked.emit('copy');
    }
  }

  protected onCancel(): void {
    this.close.emit();
  }

  /** wa.me expects digits only — strip spaces, plus signs, dashes. */
  private digitsOnly(phone: string): string {
    return phone.replace(/\D/g, '');
  }
}
