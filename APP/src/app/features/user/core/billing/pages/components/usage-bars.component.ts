import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
} from '@angular/core';

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
  template: `
    <section
      class="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-slate-400">
        Usage
      </p>
      <h2 class="mt-1 text-xl font-semibold text-zinc-900 dark:text-slate-100">
        Current period
      </h2>

      <div class="mt-6 space-y-5">
        @for (row of viewRows(); track row.label) {
          <div>
            <div class="flex items-center justify-between text-sm">
              <span class="font-medium text-zinc-700 dark:text-slate-200">
                {{ row.label }}
              </span>
              <span class="font-medium text-zinc-600 dark:text-slate-300">
                {{ row.countDisplay }}
              </span>
            </div>

            @if (row.showBar) {
              <div
                class="mt-2 h-2 w-full rounded-full bg-zinc-100 dark:bg-slate-700 overflow-hidden"
              >
                <div
                  class="h-full rounded-full transition-all"
                  [class.bg-emerald-500]="row.tone === 'green'"
                  [class.bg-amber-500]="row.tone === 'yellow'"
                  [class.bg-red-500]="row.tone === 'red'"
                  [style.width.%]="row.percent"
                ></div>
              </div>
            } @else if (row.tone === 'unlimited') {
              <p class="mt-2 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                Unlimited ✓
              </p>
            } @else {
              <p class="mt-2 text-xs text-zinc-500 dark:text-slate-400">
                Not included on your plan
              </p>
            }
          </div>
        }
      </div>
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
  const tone: UsageRowVM['tone'] =
    percent > 80 ? 'red' : percent >= 50 ? 'yellow' : 'green';

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
