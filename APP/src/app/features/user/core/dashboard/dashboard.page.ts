import { CommonModule, DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Router, RouterLink } from '@angular/router';

import { environment } from '../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';
import { DashboardDateRangeComponent } from './shared/dashboard-date-range.component';
import { DashboardKpiTileComponent } from './shared/dashboard-kpi-tile.component';
import { FunnelChartComponent } from './widgets/funnel-chart.component';
import { QuickActionsComponent } from './widgets/quick-actions.component';
import { TodaysFollowupsComponent } from './widgets/todays-followups.component';
import { TrendChartComponent } from './widgets/trend-chart.component';
import { WhatsAppHealthWidgetComponent } from './widgets/whatsapp-health-widget.component';

interface DashboardCard {
  key: string;
  label: string;
  value: number | string | LeaderboardEntry[];
  format: 'number' | 'currency' | 'percent' | 'text' | 'leaderboard';
  link: string | null;
  previous_value?: number | string | null;
  delta_pct?: number | null;
  delta_direction?: 'up' | 'down' | 'flat' | null;
}

interface LeaderboardEntry {
  name: string;
  count: number;
}

interface ActivityItem {
  action: string;
  entity_label: string;
  actor_name: string;
  at: string;
}

interface UpcomingAppointment {
  id: string;
  title: string;
  starts_at: string;
  with_contact_name: string;
}

interface Greeting {
  first_name: string;
  role_name: string;
  org_name: string;
}

interface DashboardSummary {
  greeting: Greeting;
  scope: 'org' | 'personal';
  cards: DashboardCard[];
  recent_activity: ActivityItem[];
  upcoming_appointments: UpcomingAppointment[];
}

/**
 * `/user/dashboard` — first page every signed-in user lands on.
 *
 * Fetches `/api/v1/dashboard/summary` once on init; renders three
 * sections (KPI cards grid + recent activity + upcoming appointments).
 * The card grid is rendered generically off `card.format` so adding a
 * new card later is one backend change plus (if a new format) one new
 * template branch — no per-card components.
 *
 * Scope (`org` vs `personal`) is decided server-side from the caller's
 * permission set. The component never branches on role name.
 */
@Component({
  selector: 'app-dashboard-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    RouterLink,
    DecimalPipe,
    DashboardDateRangeComponent,
    DashboardKpiTileComponent,
    QuickActionsComponent,
    WhatsAppHealthWidgetComponent,
    TrendChartComponent,
    FunnelChartComponent,
    TodaysFollowupsComponent,
  ],
  templateUrl: './dashboard.page.html',
})
export class DashboardPageComponent {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  /** Handle on the follow-ups widget so KPI-card clicks can drive
   *  its bucket filter without going through router state. */
  protected readonly followupsWidget = viewChild(TodaysFollowupsComponent);

  protected readonly summary = signal<DashboardSummary | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly refreshing = signal(false);

  // Hero strip surfaces the 4 highest-signal KPIs at the top of the
  // dashboard with period-over-period delta pills. Selection is keyed
  // by `scope` (server-decided from the caller's permission set) so
  // there's no role-name branching anywhere on the frontend.
  //
  // tasks/dashboard-updates Step 4 — the personal hero swaps
  // `conversion.my_rate` (a lagging metric) out for
  // `followups.pending_today` (the daily-driver number). Conversion
  // still renders in the secondary grid via the standard filter.
  private readonly HERO_KEYS: Record<'org' | 'personal', string[]> = {
    org: ['leads.pipeline_value', 'leads.new_today', 'appointments.today', 'conversion.rate'],
    personal: [
      'tasks.my_open',
      'followups.pending_today',
      'appointments.my_today',
      'leads.my_count',
    ],
  };

  /** Mapping followup-card key → widget bucket. Every entry here is
   *  handled via `onCardClick`'s scroll-and-filter path instead of a
   *  route navigation, so we know which keys to special-case in the
   *  click handler. */
  private readonly FOLLOWUP_CARD_TO_BUCKET: Record<
    string,
    'pending' | 'completed_today' | 'overdue'
  > = {
    'followups.pending_today': 'pending',
    'followups.completed_today': 'completed_today',
    'followups.overdue': 'overdue',
  };

  protected readonly heroCards = computed<DashboardCard[]>(() => {
    const s = this.summary();
    if (!s) return [];
    const keys = this.HERO_KEYS[s.scope] ?? [];
    return keys.map((k) => s.cards.find((c) => c.key === k)).filter((c): c is DashboardCard => !!c);
  });

  protected readonly secondaryCards = computed<DashboardCard[]>(() => {
    const s = this.summary();
    if (!s) return [];
    const heroKeys = new Set(this.HERO_KEYS[s.scope] ?? []);
    return s.cards.filter((c) => !heroKeys.has(c.key));
  });

  constructor() {
    this.load(false);
  }

  protected refresh(): void {
    this.load(true);
  }

  /** Follow-up cards render as buttons (no route); every other
   *  linkless card renders as a plain informational div. */
  protected isFollowupCard(card: DashboardCard): boolean {
    return card.key in this.FOLLOWUP_CARD_TO_BUCKET;
  }

  /** Handle KPI-card clicks: follow-up cards jump to the widget +
   *  apply the matching bucket filter; every other card with a
   *  `link` navigates normally (routerLink handles that inline in
   *  the template — this method only runs for follow-up cards). */
  protected onCardClick(card: DashboardCard): void {
    const bucket = this.FOLLOWUP_CARD_TO_BUCKET[card.key];
    if (!bucket) return;
    this.followupsWidget()?.setBucket(bucket);
    // scrollIntoView on the anchor id set in the template.
    document
      .getElementById('todays-followups-widget')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  private load(isRefresh: boolean): void {
    if (isRefresh) {
      this.refreshing.set(true);
    } else {
      this.loading.set(true);
    }
    this.error.set(null);

    this.http
      .get<DashboardSummary>(`${environment.apiBaseUrl}/dashboard/summary`)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this.summary.set(s);
          this.loading.set(false);
          this.refreshing.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? "Couldn't load your dashboard.");
          this.loading.set(false);
          this.refreshing.set(false);
        },
      });
  }

  /** Format a currency value. Org's currency code isn't on the `/me`
   *  response yet, so we default to INR. Extending OrgSummary later
   *  will let this respect the per-org code. */
  protected formatCurrency(value: number | string | LeaderboardEntry[]): string {
    const n = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(n)) return String(value);
    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency: 'INR',
        maximumFractionDigits: 0,
      }).format(n);
    } catch {
      return `₹${n.toLocaleString()}`;
    }
  }

  /** Coerce DashboardCard.value to a leaderboard list for the template. */
  protected asLeaderboard(value: unknown): LeaderboardEntry[] {
    return Array.isArray(value) ? (value as LeaderboardEntry[]) : [];
  }

  /** Relative time like "2h ago", "yesterday", "3d ago". */
  protected relativeTime(iso: string): string {
    const then = new Date(iso).getTime();
    const now = Date.now();
    const diffMs = now - then;
    if (diffMs < 0) return new Date(iso).toLocaleString();
    const min = Math.floor(diffMs / 60000);
    if (min < 1) return 'just now';
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const d = Math.floor(hr / 24);
    if (d === 1) return 'yesterday';
    if (d < 7) return `${d}d ago`;
    return new Date(iso).toLocaleDateString();
  }

  /** A short human-readable action label ("created a lead", "scheduled appointment"). */
  protected actionLabel(action: string): string {
    const tail = action.split('.').slice(1).join(' ');
    const mod = action.split('.')[0];
    const verb = tail.replace(/_/g, ' ') || 'updated';
    const noun = mod.replace(/s$/, '').replace(/_/g, ' ');
    return `${verb} ${noun}`;
  }
}
