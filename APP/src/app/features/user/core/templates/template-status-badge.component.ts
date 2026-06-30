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

const INTERNAL: Record<TemplateInternalStatus, BadgeDescriptor> = {
  draft: { label: 'Draft', classes: 'bg-zinc-100 text-zinc-700 ring-zinc-200' },
  in_review: {
    label: 'In review',
    classes: 'bg-amber-50 text-amber-700 ring-amber-200',
  },
  approved: {
    label: 'Approved',
    classes: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  },
  published: {
    label: 'Published',
    classes: 'bg-blue-50 text-blue-700 ring-blue-200',
  },
  archived: {
    label: 'Archived',
    classes: 'bg-zinc-100 text-zinc-500 ring-zinc-300',
  },
};

const EXTERNAL: Record<TemplateExternalStatus, BadgeDescriptor | null> = {
  // n_a renders nothing — the channel doesn't need external review.
  n_a: null,
  pending: {
    label: 'Pending review',
    classes: 'bg-amber-50 text-amber-700 ring-amber-200',
  },
  approved: {
    label: 'Provider approved',
    classes: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  },
  rejected: {
    label: 'Provider rejected',
    classes: 'bg-rose-50 text-rose-700 ring-rose-200',
  },
  paused: {
    label: 'Provider paused',
    classes: 'bg-orange-50 text-orange-700 ring-orange-200',
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

  protected readonly descriptor = computed<BadgeDescriptor | null>(() => {
    const internal = this.internal();
    if (internal) return INTERNAL[internal] ?? null;
    const external = this.external();
    if (external) return EXTERNAL[external];
    return null;
  });
}
