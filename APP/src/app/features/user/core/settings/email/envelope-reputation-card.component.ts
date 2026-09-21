/**
 * One dashboard card per (envelope × domain). Rendered by
 * ``ReputationDashboardTabComponent``.
 *
 * Contract:
 *
 *   * Name + type badge (Platform / Own domain).
 *   * Warmup progress bar coloured by state (ok = green, warned =
 *     amber, blocked = red).
 *   * "Daily sent: 123 / 1000" progress bar.
 *   * Four metric tiles: delivered / bounced / complained /
 *     unsubscribed, each with its 24h count + rate where applicable.
 *   * State badge — matches the amber-standard-warning-banner
 *     pattern (memory ``feedback_standard_warning_banner_pattern``)
 *     when state = warned/blocked.
 *   * Blocked-until countdown — refreshed every second by the parent
 *     component's tick signal.
 */
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import type { EnvelopeReputation } from './reputation.service';

@Component({
  selector: 'app-envelope-reputation-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './envelope-reputation-card.component.html',
})
export class EnvelopeReputationCardComponent {
  /** The row this card renders. Required — no synthesis at the
   * component level, all pristine handling is server-side. */
  readonly row = input.required<EnvelopeReputation>();

  /** Milliseconds since epoch — the parent ticks this every second
   * so ``blockedCountdown`` re-computes without an internal timer. */
  readonly nowMs = input.required<number>();

  /** Envelope display label. ``platform_from`` reads as "Platform
   * from" in ordinary sentences but "Platform envelope" is clearer
   * in the badge. */
  readonly envelopeLabel = computed(() => {
    const kind = this.row().envelope_type;
    return kind === 'platform_from' ? 'Platform envelope' : 'Own domain';
  });

  /** Domain string (own_domain) or "Shared platform" (platform_from). */
  readonly cardTitle = computed(() => {
    const r = this.row();
    if (r.envelope_type === 'own_domain') {
      return r.domain_string ?? 'Own domain';
    }
    return 'Shared platform sending';
  });

  /** Tailwind classes for the state pill. Green / amber / red match
   * the standard-warning-banner palette. */
  readonly stateBadgeClasses = computed(() => {
    switch (this.row().reputation_state) {
      case 'ok':
        return 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
      case 'warned':
        return 'bg-amber-500/10 text-amber-400 border border-amber-500/20';
      case 'blocked':
        return 'bg-red-500/10 text-red-400 border border-red-500/20';
    }
  });

  readonly stateLabel = computed(() => {
    switch (this.row().reputation_state) {
      case 'ok':
        return 'OK';
      case 'warned':
        return 'Warned';
      case 'blocked':
        return 'Blocked';
    }
  });

  /** Progress-bar colour for the warmup rung — green while ok,
   * amber on warned, red on blocked. */
  readonly warmupBarClass = computed(() => {
    switch (this.row().reputation_state) {
      case 'ok':
        return 'bg-emerald-500';
      case 'warned':
        return 'bg-amber-500';
      case 'blocked':
        return 'bg-red-500';
    }
  });

  /** Daily-sent bar shows as amber when the row is over 80% of its
   * cap so the Owner sees "you're about to hit the ceiling" without
   * reading the numbers. */
  readonly dailySentBarClass = computed(() => {
    const r = this.row();
    if (r.daily_cap <= 0) return 'bg-emerald-500';
    const pct = (r.daily_sent / r.daily_cap) * 100;
    if (pct >= 100) return 'bg-red-500';
    if (pct >= 80) return 'bg-amber-500';
    return 'bg-emerald-500';
  });

  readonly dailySentPct = computed(() => {
    const r = this.row();
    if (r.daily_cap <= 0) return 0;
    return Math.min(100, (r.daily_sent / r.daily_cap) * 100);
  });

  /** Formatted percent for the rate tiles. 0.003 → "0.30%". */
  readonly complaintRateLabel = computed(() => `${(this.row().complaint_rate * 100).toFixed(2)}%`);
  readonly bounceRateLabel = computed(() => `${(this.row().bounce_rate * 100).toFixed(2)}%`);

  /** "in 3h 12m" style. Empty string when not blocked or already
   * elapsed (the hourly sweeper will flip state on its next tick). */
  readonly blockedCountdown = computed(() => {
    const r = this.row();
    if (r.reputation_state !== 'blocked' || !r.blocked_until) return '';
    const remainingMs = new Date(r.blocked_until).getTime() - this.nowMs();
    if (remainingMs <= 0) return 'unblocking...';
    const totalSeconds = Math.floor(remainingMs / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
    return `${minutes}m ${seconds}s`;
  });
}
