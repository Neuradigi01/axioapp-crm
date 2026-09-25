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
    classes: 'bg-surface-2 text-default border-subtle',
  },
  active: {
    label: 'Active',
    classes: 'bg-emerald-500/10 text-emerald-700 ring-emerald-500/20',
  },
  paused: {
    label: 'Paused',
    classes: 'bg-amber-500/10 text-amber-700 ring-amber-500/20',
  },
  archived: {
    label: 'Archived',
    classes: 'bg-surface-2 text-muted border-subtle',
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
