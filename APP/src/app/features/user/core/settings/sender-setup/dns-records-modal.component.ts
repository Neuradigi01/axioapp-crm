/**
 * DNS records modal — copy-paste sheet for SPF, DKIM, DMARC (Step 07b).
 *
 * Purely presentational. Parent passes the composed records; each row
 * offers a "Copy value" button that shells to the Clipboard API. If
 * the API is unavailable (rare — modern Chromium/Safari support it),
 * the button falls back to selecting the text so the operator can
 * Ctrl-C it manually.
 */
import { ChangeDetectionStrategy, Component, input, output, signal } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { EmailSenderDnsRecord } from '../../services/email-sender-setup-api.service';

@Component({
  selector: 'app-sender-dns-records-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './dns-records-modal.component.html',
})
export class DnsRecordsModalComponent {
  readonly domain = input.required<string>();
  readonly records = input.required<EmailSenderDnsRecord[]>();
  readonly closed = output<void>();

  protected readonly copiedPurpose = signal<string | null>(null);

  onBackdropClick(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.closed.emit();
    }
  }

  purposeLabel(purpose: EmailSenderDnsRecord['purpose']): string {
    if (purpose === 'spf') return 'SPF';
    if (purpose === 'dkim') return 'DKIM';
    return 'DMARC';
  }

  purposeBlurb(purpose: EmailSenderDnsRecord['purpose']): string {
    if (purpose === 'spf') return 'Authorises our senders to relay from your domain.';
    if (purpose === 'dkim')
      return 'Cryptographic signature — proves the mail was not tampered with.';
    return 'Policy that tells recipients what to do with mail that fails SPF or DKIM.';
  }

  async copy(record: EmailSenderDnsRecord): Promise<void> {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(record.value);
      } else {
        // Legacy fallback — should almost never fire.
        const ta = document.createElement('textarea');
        ta.value = record.value;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      this.copiedPurpose.set(record.purpose);
      window.setTimeout(() => {
        if (this.copiedPurpose() === record.purpose) {
          this.copiedPurpose.set(null);
        }
      }, 1600);
    } catch {
      // Silent — the value is right there for manual copy.
    }
  }
}
