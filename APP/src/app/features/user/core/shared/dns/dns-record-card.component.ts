/**
 * DNS record card — one visual row per DNS record the operator needs
 * to publish. Shared under ``features/user/core/shared/dns/`` so both
 * Sending Domains (Step 7) and a future Custom Inbound Domain tab
 * can render the same shape (memory ``feedback_reusable_code_lives_in_shared``).
 *
 * Layout: three key/value stacks (Type, Host, Value) — plus a
 * Priority stack only when ``record.record_type === 'MX'``. Every
 * value has a copy-to-clipboard button (memory-styled amber toast
 * confirmation on success is the caller's job — this component just
 * emits a ``copied`` event carrying which field was copied).
 *
 * ``valid`` verdict maps to a colour dot: green for ``valid``, grey
 * for ``unknown`` (never verified yet), amber for anything else
 * (invalid / bespoke Mailgun state).
 */
import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import type { DnsRecord } from '../../settings/email/models';

@Component({
  selector: 'app-dns-record-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './dns-record-card.component.html',
})
export class DnsRecordCardComponent {
  readonly record = input.required<DnsRecord>();
  /** Emitted whenever the copy button is clicked. The value is the
   * exact string that just landed in the clipboard so the parent can
   * fire a toast without re-reading the input. */
  readonly copied = output<{ field: 'host' | 'value'; text: string }>();

  /** True only when the record is an MX row — priority column is
   * hidden otherwise (SPF / DKIM / DMARC have no priority). */
  readonly isMx = computed(() => (this.record().record_type ?? '').toUpperCase() === 'MX');

  /** Colour-dot class for the valid verdict. Fail-soft on unknown
   * strings from Mailgun (future verdict values map to amber). */
  readonly verdictClass = computed<string>(() => {
    const verdict = (this.record().valid ?? '').toLowerCase();
    if (verdict === 'valid') return 'bg-emerald-500';
    if (verdict === 'unknown') return 'bg-zinc-400';
    return 'bg-amber-500';
  });

  async copyHost(): Promise<void> {
    const host = this.record().name ?? '';
    if (!host) return;
    await navigator.clipboard.writeText(host);
    this.copied.emit({ field: 'host', text: host });
  }

  async copyValue(): Promise<void> {
    const value = this.record().value ?? '';
    if (!value) return;
    await navigator.clipboard.writeText(value);
    this.copied.emit({ field: 'value', text: value });
  }
}
