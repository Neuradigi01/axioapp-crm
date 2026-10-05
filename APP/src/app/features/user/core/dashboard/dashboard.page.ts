import { CommonModule, DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  HostListener,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Router, RouterLink } from '@angular/router';

import { environment } from '../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../auth/auth.service';
import { DashboardDateRangeComponent } from './shared/dashboard-date-range.component';
import { DashboardKpiTileComponent } from './shared/dashboard-kpi-tile.component';
import { DealPipelineStripComponent } from './widgets/deal-pipeline-strip.component';
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
  /** Present only when the entity still exists (deep-link target). */
  entity_type?: string | null;
  entity_id?: string | null;
}

/** Past-tense phrase per audit verb ("leads.marked_done" → "completed"). */
const ACTION_VERBS: Record<string, string> = {
  created: 'created',
  updated: 'updated',
  deleted: 'deleted',
  rescheduled: 'rescheduled',
  reassigned: 'reassigned',
  marked_done: 'completed',
  marked_missed: 'marked as missed',
  auto_missed: 'auto-missed',
  quick_registered: 'registered',
  converted: 'converted',
  checked_out: 'checked out',
  opt_in_changed: 'changed opt-in for',
  outcome_updated: 'updated the outcome of',
  'import.uploaded': 'uploaded an import of',
  'import.committed': 'imported',
  'import.cancelled': 'cancelled an import of',
};

/** Audit module → singular noun. */
const ACTION_NOUNS: Record<string, string> = {
  leads: 'lead',
  contacts: 'contact',
  appointments: 'appointment',
  tasks: 'task',
  calls: 'call',
  walk_ins: 'walk-in',
  walkins: 'walk-in',
  reviews: 'review',
  invitations: 'invitation',
  roles: 'role',
  ownership: 'ownership',
};

/** Auto-refresh when the tab regains focus after this long. */
const STALE_AFTER_MS = 5 * 60_000;

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
    DealPipelineStripComponent,
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
  private readonly auth = inject(FurnitureAuthService);

  /** Handle on the follow-ups widget so KPI-card clicks can drive
   *  its bucket filter without going through router state. */
  protected readonly followupsWidget = viewChild(TodaysFollowupsComponent);

  protected readonly summary = signal<DashboardSummary | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly refreshing = signal(false);

  /** When the summary last loaded successfully (drives "Updated …"). */
  protected readonly loadedAt = signal<number | null>(null);
  /** Minute tick so the "Updated Xm ago" label stays truthful. */
  private readonly nowTick = signal(Date.now());
  protected readonly updatedLabel = computed<string | null>(() => {
    const at = this.loadedAt();
    if (at === null) return null;
    const min = Math.floor((this.nowTick() - at) / 60_000);
    if (min < 1) return 'Updated just now';
    if (min < 60) return `Updated ${min}m ago`;
    return `Updated ${Math.floor(min / 60)}h ago`;
  });

  /** Coming back to a tab left open for a while refetches everything —
   *  otherwise the morning's numbers sit there all afternoon. */
  @HostListener('document:visibilitychange')
  protected onVisibilityChange(): void {
    if (document.hidden) return;
    this.nowTick.set(Date.now());
    const at = this.loadedAt();
    if (at !== null && Date.now() - at > STALE_AFTER_MS && !this.refreshing()) {
      this.refresh();
    }
  }

  /** Monotonic counter bumped on every user-initiated Refresh click.
   *  Trend / funnel / follow-ups widgets consume this via an `input`
   *  and refetch on change so a single "Refresh" click reloads the
   *  entire dashboard instead of just `/dashboard/summary`. Starts at
   *  0 so the initial value never fires a duplicate fetch on mount. */
  protected readonly refreshTick = signal(0);

  /** Which slice of appointments to fetch for the Appointments widget.
   *  Default matches the widget's default chip. Flipping this triggers
   *  a re-fetch of `/dashboard/summary?upcoming_scope=…`. */
  protected readonly appointmentsScope = signal<'today' | 'next5'>('today');

  protected readonly appointmentChips: ReadonlyArray<{
    readonly value: 'today' | 'next5';
    readonly label: string;
  }> = [
    { value: 'today', label: 'Today' },
    { value: 'next5', label: 'Next 5' },
  ];

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

  /** Time-of-day greeting word to match AIXO's "Good afternoon, X". */
  protected readonly timeOfDayGreeting = computed<string>(() => {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 18) return 'Good afternoon';
    return 'Good evening';
  });

  /** Pack/template slug → display name for the AIXO subline "Here's
   *  what's moving in your X workspace." Falls back to the raw slug
   *  title-cased if unknown so a new pack still renders sensibly. */
  private readonly TEMPLATE_LABELS: Record<string, string> = {
    base: 'CRM',
    real_estate: 'Real Estate',
    furniture: 'Furniture',
    clinic: 'Clinic',
    salon: 'Salon',
    services: 'Services',
  };

  protected readonly workspaceLabel = computed<string>(() => {
    const tid = this.auth.currentOrg()?.template_id;
    if (!tid) return 'CRM';
    if (tid in this.TEMPLATE_LABELS) return this.TEMPLATE_LABELS[tid];
    return tid.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  });

  protected readonly secondaryCards = computed<DashboardCard[]>(() => {
    const s = this.summary();
    if (!s) return [];
    const heroKeys = new Set(this.HERO_KEYS[s.scope] ?? []);
    return s.cards.filter((c) => !heroKeys.has(c.key));
  });

  constructor() {
    this.load(false);
    const timer = setInterval(() => this.nowTick.set(Date.now()), 60_000);
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }

  protected refresh(): void {
    this.load(true);
    // Fan out to every child widget by bumping the tick signal — their
    // input-linked effects re-fire and hit their own endpoints. Keeps
    // widget owners in charge of what to refetch (trend obeys metric
    // + range, funnel obeys range, follow-ups is bucket-scoped) while
    // one button reloads the whole page from the user's perspective.
    this.refreshTick.update((n) => n + 1);
  }

  /** Flip the Appointments widget's Today ↔ Next 5 toggle. Refetches
   *  the summary payload with the new query param so the server does
   *  the filter — a client-side slice would truncate at 5 rows and
   *  misreport busy days. */
  protected setAppointmentsScope(scope: 'today' | 'next5'): void {
    if (this.appointmentsScope() === scope) return;
    this.appointmentsScope.set(scope);
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

  /** Last-write-wins guard — rapid Today ↔ Next 5 flips could otherwise
   *  paint the slower, older response. */
  private loadSeq = 0;

  private load(isRefresh: boolean): void {
    const seq = ++this.loadSeq;
    if (isRefresh) {
      this.refreshing.set(true);
    } else {
      this.loading.set(true);
    }
    this.error.set(null);

    this.http
      .get<DashboardSummary>(`${environment.apiBaseUrl}/dashboard/summary`, {
        params: { upcoming_scope: this.appointmentsScope() },
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          if (seq !== this.loadSeq) return;
          this.summary.set(s);
          this.loadedAt.set(Date.now());
          this.nowTick.set(Date.now());
          this.loading.set(false);
          this.refreshing.set(false);
        },
        error: (err: HttpErrorResponse) => {
          if (seq !== this.loadSeq) return;
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

  /** Human phrase for an audit action: "leads.created" → "created a lead". */
  protected actionLabel(action: string): string {
    const [mod, ...rest] = action.split('.');
    const tail = rest.join('.');
    const verb = ACTION_VERBS[tail] ?? (tail.replace(/[._]/g, ' ') || 'updated');
    const noun = ACTION_NOUNS[mod] ?? mod.replace(/s$/, '').replace(/_/g, ' ');
    const article = /^[aeiou]/i.test(noun) ? 'an' : 'a';
    return `${verb} ${article} ${noun}`;
  }

  /** Fallback labels look like `task:25a0db3c` (entity since deleted) —
   *  the phrase already names the type, so show nothing extra. */
  protected activityTarget(a: ActivityItem): string | null {
    return /^[a-z_]+:[0-9a-f]{8}$/.test(a.entity_label) ? null : a.entity_label;
  }

  /** Router link for an activity row, when its entity still exists. */
  protected activityLink(
    a: ActivityItem,
  ): { path: string[]; query: Record<string, string> | null } | null {
    if (!a.entity_id) return null;
    switch (a.entity_type) {
      case 'lead':
        return { path: ['/user/leads', a.entity_id], query: null };
      case 'contact':
        return { path: ['/user/contacts', a.entity_id], query: null };
      case 'task':
        return { path: ['/user/tasks'], query: { task: a.entity_id } };
      case 'appointment':
        return { path: ['/user/appointments'], query: null };
      default:
        return null;
    }
  }
}
