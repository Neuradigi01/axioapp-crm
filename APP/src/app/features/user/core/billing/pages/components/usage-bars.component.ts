import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { UsageRow } from '../../types/subscription.types';

/** Human-readable labels for the metered resources surfaced by
 *  `GET /subscriptions/current`. Resources not in this map fall back
 *  to a Title Cased version of the resource key so an unknown future
 *  resource still renders, just less prettily. */
const RESOURCE_LABELS: Record<string, string> = {
  contacts: 'Contacts',
  leads_per_month: 'Leads this month',
  storage_mb: 'Storage',
  automation_runs_per_month: 'Automations this month',
  form_submissions_per_month: 'Form submissions this month',
  email_sends_per_month: 'Emails this month',
  sms_sends_per_month: 'SMS this month',
  api_calls_per_day: 'API calls today',
};

/** Resources whose value is in MB; rendered as `8 MB / 100 MB`. */
const MB_RESOURCES = new Set<string>(['storage_mb']);

interface UsageRowVM {
  label: string;
  /** Display string like "47 / 500" or "8 MB / 100 MB" or "0 / unlimited". */
  countDisplay: string;
  /** Percent 0–100 used for the bar width; clamped at 100. */
  percent: number;
  /** Whether to render the bar at all (false for unlimited / cap=0). */
  showBar: boolean;
  /** Colour band — green / yellow / red. */
  tone: 'green' | 'yellow' | 'red' | 'unlimited';
}

/**
 * Per-resource utilisation bars on the Billing settings page.
 *
 * Colour bands match the spec: green < 50%, yellow 50-80%, red > 80%.
 * `is_unlimited: true` rows render "Unlimited ✓" without a bar.
 * Zero-cap rows (e.g. `automation_runs_per_month` on the Trial plan)
 * show "Not included" so the customer doesn't see a 0/0 numerator.
 */
@Component({
  selector: 'crm-usage-bars',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    <section
      class="flex h-full flex-col rounded-xl border border-subtle bg-surface p-6 shadow-sm dark:border-subtle dark:bg-accent"
    >
      <div class="flex items-center gap-3">
        <div
          class="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-50 text-violet-600 ring-1 ring-violet-100 dark:bg-violet-950 dark:text-violet-300 dark:ring-violet-900"
        >
          <lucide-icon name="trending-up" size="18" aria-hidden="true"></lucide-icon>
        </div>
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-muted dark:text-faint">
            Usage
          </p>
          <h2 class="text-base font-semibold text-default dark:text-default">Current period</h2>
        </div>
      </div>

      @if (viewRows().length === 0) {
        <p class="mt-6 text-sm text-muted dark:text-faint">No metered resources on your plan.</p>
      } @else {
        <div class="mt-5 space-y-4">
          @for (row of viewRows(); track row.label) {
            <div>
              <div class="flex items-center justify-between text-sm">
                <span class="font-medium text-default dark:text-default">
                  {{ row.label }}
                </span>
                <span class="tabular-nums text-muted dark:text-muted">
                  {{ row.countDisplay }}
                  @if (row.showBar) {
                    <span class="ml-1 text-xs text-faint dark:text-muted">
                      ({{ row.percent }}%)
                    </span>
                  }
                </span>
              </div>

              @if (row.showBar) {
                <div
                  class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-2 dark:bg-surface"
                >
                  <div
                    class="h-full rounded-full transition-all"
                    [class.bg-emerald-500]="row.tone === 'green'"
                    [class.bg-amber-500]="row.tone === 'yellow'"
                    [class.bg-rose-500]="row.tone === 'red'"
                    [style.width.%]="row.percent"
                  ></div>
                </div>
              } @else if (row.tone === 'unlimited') {
                <p class="mt-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                  Unlimited
                </p>
              } @else {
                <p class="mt-1 text-xs text-muted dark:text-faint">Not included on your plan</p>
              }
            </div>
          }
        </div>
      }
    </section>
  `,
})
export class UsageBarsComponent {
  readonly usage = input.required<readonly UsageRow[]>();

  protected readonly viewRows = computed<readonly UsageRowVM[]>(() =>
    this.usage().map(toViewModel),
  );
}

// ---------------------------------------------------------------------------
// Pure helpers — module-private so the template's signal chain stays
// noise-free.
// ---------------------------------------------------------------------------

function toViewModel(row: UsageRow): UsageRowVM {
  const label = RESOURCE_LABELS[row.resource] ?? titleCase(row.resource);
  const isMb = MB_RESOURCES.has(row.resource);

  if (row.is_unlimited) {
    return {
      label,
      countDisplay: `${formatNumber(row.current, isMb)} used`,
      percent: 0,
      showBar: false,
      tone: 'unlimited',
    };
  }

  if (row.cap === 0) {
    return {
      label,
      countDisplay: '—',
      percent: 0,
      showBar: false,
      tone: 'green',
    };
  }

  const percent = Math.min(100, Math.round((row.current / row.cap) * 100));
  const tone: UsageRowVM['tone'] = percent > 80 ? 'red' : percent >= 50 ? 'yellow' : 'green';

  return {
    label,
    countDisplay: `${formatNumber(row.current, isMb)} / ${formatNumber(row.cap, isMb)}`,
    percent,
    showBar: true,
    tone,
  };
}

function formatNumber(value: number, isMb: boolean): string {
  if (isMb) {
    return `${value} MB`;
  }
  return value.toLocaleString('en-US');
}

function titleCase(raw: string): string {
  return raw
    .split(/[_\s]+/)
    .map((part) => (part.length === 0 ? part : part[0].toUpperCase() + part.slice(1)))
    .join(' ');
}
