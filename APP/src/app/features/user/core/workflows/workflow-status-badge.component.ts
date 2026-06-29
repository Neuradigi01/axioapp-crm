import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import type { WorkflowStatus } from './workflows-api.service';

/**
 * Workflow status badge. Mirrors the `template-status-badge` palette
 * conventions: draft = zinc, active = emerald, paused = amber,
 * archived = zinc (lighter). Tailwind-only.
 */
interface BadgeDescriptor {
  label: string;
  classes: string;
}

const STATUS_BADGES: Record<WorkflowStatus, BadgeDescriptor> = {
  draft: {
    label: 'Draft',
    classes: 'bg-zinc-100 text-zinc-700 ring-zinc-200',
  },
  active: {
    label: 'Active',
    classes: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  },
  paused: {
    label: 'Paused',
    classes: 'bg-amber-50 text-amber-700 ring-amber-200',
  },
  archived: {
    label: 'Archived',
    classes: 'bg-zinc-100 text-zinc-500 ring-zinc-300',
  },
};


@Component({
  selector: 'app-workflow-status-badge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './workflow-status-badge.component.html',
})
export class WorkflowStatusBadgeComponent {
  readonly status = input<WorkflowStatus | null>(null);

  protected readonly descriptor = computed<BadgeDescriptor | null>(() => {
    const value = this.status();
    if (!value) return null;
    return STATUS_BADGES[value] ?? null;
  });
}
