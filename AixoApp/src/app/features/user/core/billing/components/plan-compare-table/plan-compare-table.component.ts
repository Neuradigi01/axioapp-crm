import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { PlanCatalogEntry } from '../../types/subscription.types';

/**
 * Plan comparison table — reusable component that renders a
 * "features × plans" matrix so operators can see what's included in
 * each plan at a glance.
 *
 * Consumes the same ``PlanCatalogEntry[]`` shape returned by
 * ``GET /api/v1/plans``; no extra fetches. Feature keys are grouped
 * into human-readable categories via :const:`CATEGORIES` and mapped
 * to prettier labels — the raw wire keys (``automation.workflows``,
 * ``integrations.whatsapp``, …) never leak to the operator.
 *
 * Used from:
 *   * ``billing.page.html`` — always visible under the current-plan
 *     card so operators can compare without opening the upgrade flow.
 *   * ``upgrade-modal.component.html`` — inside an expandable "Compare
 *     plans" toggle so a decision-maker mid-checkout can quickly see
 *     what they're paying for without leaving the modal.
 */

interface FeatureRow {
  readonly key: string;
  readonly label: string;
}

interface CategorySection {
  readonly label: string;
  readonly features: readonly FeatureRow[];
}

// Curated subset of ``plans.yaml -> features.*`` keys grouped for the
// UI. Order matters — this is the row order shown to the operator.
// Any key missing from a plan's ``features`` map renders as "not
// included" (safe default). New features added to the yaml but not
// listed here simply won't appear in the comparison until added below.
const CATEGORIES: readonly CategorySection[] = [
  {
    label: 'Core CRM',
    features: [
      { key: 'contacts.write', label: 'Contacts & leads' },
      { key: 'tasks.write', label: 'Tasks & pipelines' },
      { key: 'walkins.read', label: 'Walk-ins' },
    ],
  },
  {
    label: 'Automation & Messaging',
    features: [
      { key: 'automation.workflows', label: 'Workflow automation' },
      { key: 'conversations.unified_inbox', label: 'Unified inbox (WhatsApp + Email)' },
      { key: 'integrations.whatsapp', label: 'WhatsApp Business integration' },
      { key: 'integrations.email_imap_smtp', label: 'Email integration (IMAP / SMTP)' },
      { key: 'campaigns.email', label: 'Email campaigns' },
      { key: 'calls.recording', label: 'Call recording' },
    ],
  },
  {
    label: 'Ads & Growth',
    features: [
      { key: 'ads.google_webhook', label: 'Google Ads lead capture' },
      { key: 'ads.meta_webhook', label: 'Meta Ads lead capture' },
    ],
  },
  {
    label: 'Enterprise',
    features: [
      { key: 'sso.saml', label: 'SSO (SAML)' },
      { key: 'audit.full_log', label: 'Full audit log' },
      { key: 'multi_branch', label: 'Multi-branch' },
      { key: 'white_label', label: 'White-label' },
    ],
  },
];

interface CapRow {
  readonly key: string;
  readonly label: string;
  readonly format: 'count' | 'storage_mb';
}

// Numeric caps shown at the bottom. ``-1`` is the "unlimited" sentinel
// from the yaml — rendered as "Unlimited" instead of a huge number.
const CAP_ROWS: readonly CapRow[] = [
  { key: 'contacts', label: 'Contacts', format: 'count' },
  { key: 'leads_per_month', label: 'Leads / month', format: 'count' },
  { key: 'storage_mb', label: 'Storage', format: 'storage_mb' },
  { key: 'pipelines', label: 'Pipelines', format: 'count' },
  { key: 'form_widgets', label: 'Form widgets', format: 'count' },
  { key: 'automation_runs_per_month', label: 'Automation runs / month', format: 'count' },
  { key: 'email_sends_per_month', label: 'Email sends / month', format: 'count' },
  { key: 'sms_sends_per_month', label: 'SMS sends / month', format: 'count' },
];

@Component({
  selector: 'crm-plan-compare-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './plan-compare-table.component.html',
})
export class PlanCompareTableComponent {
  /** Public plans in display order. Caller fetches once via
   *  ``BillingApiService.getPlans()``; component just renders. */
  readonly plans = input.required<readonly PlanCatalogEntry[]>();

  /** Optional: highlight which plan the org is currently on so the
   *  "you're here" indicator lands in the right column. Match on
   *  ``PlanCatalogEntry.code``; pass ``null`` from contexts where
   *  there's no "current" concept (e.g. the pre-purchase modal). */
  readonly currentPlanCode = input<string | null>(null);

  protected readonly categories = CATEGORIES;
  protected readonly capRows = CAP_ROWS;

  /** Sort by ``display_order`` so ``Basic → Standard → Enterprise``
   *  stays consistent regardless of API response order. Filtered
   *  through ``is_public`` defensively even though the endpoint
   *  already drops the trial plan. */
  protected readonly visiblePlans = computed(() =>
    [...this.plans()]
      .filter((p) => p.is_public !== false)
      .sort((a, b) => a.display_order - b.display_order),
  );

  protected hasFeature(plan: PlanCatalogEntry, key: string): boolean {
    return plan.features?.[key] === true;
  }

  protected formatCap(plan: PlanCatalogEntry, row: CapRow): string {
    const raw = plan.caps?.[row.key];
    if (raw === undefined || raw === null) return '—';
    if (raw === -1) return 'Unlimited';
    if (row.format === 'storage_mb') return this._formatStorageMb(raw);
    return this._formatCount(raw);
  }

  private _formatCount(n: number): string {
    // Thousand separators via toLocaleString — matches the CRM's INR
    // formatting on invoices so operators see consistent number styling.
    return n.toLocaleString('en-IN');
  }

  private _formatStorageMb(mb: number): string {
    if (mb >= 1024) {
      const gb = mb / 1024;
      // Whole GB shows as "5 GB"; fractional keeps 1 decimal ("1.5 GB").
      return Number.isInteger(gb) ? `${gb} GB` : `${gb.toFixed(1)} GB`;
    }
    return `${mb} MB`;
  }
}
