import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import type { TemplateExternalStatus, TemplateInternalStatus } from './templates-api.service';

/**
 * Status badge — renders either an internal workflow status
 * (`draft / in_review / approved / published / archived`) or an
 * external-provider status (`n_a / pending / approved / rejected /
 * paused`). The external badge is hidden when ``n_a`` so non-WA / non-
 * SMS-DLT rows don't carry visual noise.
 *
 * One component, two inputs, mutually exclusive: callers pass either
 * `internal` or `external`, not both. Tailwind-only — no theme system
 * coupling.
 */
interface BadgeDescriptor {
  label: string;
  classes: string;
}

// The internal ``approved`` state deliberately uses "Ready to publish"
// instead of the on-wire "Approved" so it never collides with the
// external EXTERNAL[approved] badge — which also renders green and also
// used to say "Approved". Two green "Approved" badges side-by-side (one
// meaning "your team's reviewer OK'd it, awaiting Publish click", the
// other meaning "Meta/DLT OK'd it, safe to send") consistently misled
// operators into thinking a WA-pending template was ready.
const INTERNAL: Record<TemplateInternalStatus, BadgeDescriptor> = {
  draft: { label: 'Draft', classes: 'bg-surface-2 text-default border-subtle' },
  in_review: {
    label: 'In review',
    classes: 'bg-amber-500/10 text-amber-700 ring-amber-500/20',
  },
  approved: {
    label: 'Ready to publish',
    classes: 'bg-emerald-500/10 text-emerald-700 ring-emerald-500/20',
  },
  published: {
    label: 'Published',
    classes: 'bg-blue-500/10 text-blue-700 ring-blue-500/20',
  },
  archived: {
    label: 'Archived',
    classes: 'bg-surface-2 text-muted border-subtle',
  },
};

const EXTERNAL: Record<TemplateExternalStatus, BadgeDescriptor | null> = {
  // n_a renders nothing — the channel doesn't need external review.
  n_a: null,
  // Labels are single words — the column header "External" already
  // disambiguates, and "Provider approved" was too wide for narrow cells.
  pending: {
    label: 'Pending',
    classes: 'bg-amber-500/10 text-amber-700 ring-amber-500/20',
  },
  approved: {
    label: 'Approved',
    classes: 'bg-emerald-500/10 text-emerald-700 ring-emerald-500/20',
  },
  rejected: {
    label: 'Rejected',
    classes: 'bg-red-500/10 text-red-700 ring-red-500/20',
  },
  paused: {
    label: 'Paused',
    classes: 'bg-orange-500/10 text-orange-700 ring-orange-500/20',
  },
};

@Component({
  selector: 'app-template-status-badge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './template-status-badge.component.html',
})
export class TemplateStatusBadgeComponent {
  readonly internal = input<TemplateInternalStatus | null>(null);
  readonly external = input<TemplateExternalStatus | null>(null);

  /** Campaigns v1 Step 02 — Meta's rejection text, shown as a tooltip
   *  on hover / keyboard focus of a rejected badge. When null (or the
   *  status isn't ``rejected``), the badge renders as before — a
   *  plain non-interactive `<span>` with no tooltip and no aria noise. */
  readonly rejectionReason = input<string | null>(null);

  protected readonly descriptor = computed<BadgeDescriptor | null>(() => {
    const internal = this.internal();
    if (internal) return INTERNAL[internal] ?? null;
    const external = this.external();
    if (external) return EXTERNAL[external];
    return null;
  });

  /** True when the badge should offer a hover-tooltip. Only fires for
   *  externally-rejected rows that carry a non-empty reason string —
   *  everything else keeps the plain badge markup. */
  protected readonly showRejectionTooltip = computed<boolean>(() => {
    if (this.external() !== 'rejected') return false;
    const reason = this.rejectionReason();
    return !!reason && reason.trim().length > 0;
  });
}
