import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { endOfMonth, endOfWeek, format, isSameDay, startOfMonth, startOfWeek } from 'date-fns';
import { forkJoin, of } from 'rxjs';
import { catchError, distinctUntilChanged } from 'rxjs/operators';

import { ActivatedRoute, Router } from '@angular/router';

import { FurnitureAuthService } from '../auth/auth.service';
import { BulkActionBarComponent } from '../shared/bulk-action-bar/bulk-action-bar.component';
import { CalendarComponent, CalendarEvent } from '../shared/calendar/calendar.component';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import { ContactsApiService } from '../contacts/contacts-api.service';
import { MailLinkDirective } from '../shared/directives/mail-link.directive';
import { PhoneLinkDirective } from '../shared/directives/phone-link.directive';
import {
  UrlFilterStateConfig,
  UrlFilterStateDirective,
} from '../shared/directives/url-filter-state.directive';
import { WhatsappLinkDirective } from '../shared/directives/whatsapp-link.directive';
import { OwnerColor, ownerColor } from '../shared/owner-color.util';
import { RelativeTimePipe } from '../shared/pipes/relative-time.pipe';
import {
  ReassignConfirm,
  ReassignModalComponent,
} from '../shared/reassign-modal/reassign-modal.component';
import { ListPageState } from '../shared/services/list-page.service';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import {
  Appointment,
  AppointmentSortKey,
  AppointmentsApiService,
  SortOrder,
} from './appointments-api.service';
import { AppointmentPopoverComponent } from './appointment-popover.component';
import { BookAppointmentModalComponent } from './book-appointment-modal.component';
import { RescheduleConfirm, RescheduleModalComponent } from './reschedule-modal.component';
import { extractApiError } from '@core/services/api-error.util';
import { initials } from '@core/services/text.util';

interface ContactSummary {
  id: string;
  full_name: string;
  phone: string | null;
  email: string | null;
}

type AppointmentStatusValue = 'scheduled' | 'completed' | 'no_show' | 'cancelled';
type StatusFilter = 'all' | 'upcoming' | AppointmentStatusValue;

const FILTER_CHIPS: ReadonlyArray<{ id: StatusFilter; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'upcoming', label: 'Upcoming' },
  { id: 'completed', label: 'Completed' },
  { id: 'no_show', label: 'No-show' },
  { id: 'cancelled', label: 'Cancelled' },
];

class AppointmentsListState extends ListPageState<Appointment> {}

@Component({
  selector: 'app-appointments-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LucideAngularModule,
    ReactiveFormsModule,
    CalendarComponent,
    BookAppointmentModalComponent,
    BulkActionBarComponent,
    ReassignModalComponent,
    ConfirmDialogComponent,
    RescheduleModalComponent,
    AppointmentPopoverComponent,
    PhoneLinkDirective,
    WhatsappLinkDirective,
    MailLinkDirective,
    UrlFilterStateDirective,
    RelativeTimePipe,
  ],
  providers: [AppointmentsListState],
  templateUrl: './appointments.page.html',
})
export class AppointmentsPageComponent {
  protected readonly ownerColor = ownerColor;
  protected readonly initials = initials;

  private readonly api = inject(AppointmentsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly state = inject(AppointmentsListState);

  /** List vs calendar — controlled by the toggle at the top of the page. */
  readonly view = signal<'list' | 'calendar'>('list');

  /** Calendar's currently-shown month. */
  readonly viewMonth = signal<Date>(new Date());

  /** Currently-clicked day (right panel shows this day's appointments). */
  readonly selectedDay = signal<Date>(new Date());

  readonly contactsById = signal<Record<string, ContactSummary>>({});

  /** Modal state. */
  readonly modalOpen = signal(false);

  // --- Filter + sort + scope ---------------------------------------------

  readonly sortKey = signal<AppointmentSortKey>('scheduled_at');
  readonly sortOrder = signal<SortOrder>('asc');
  readonly statusFilter = signal<StatusFilter>('all');
  readonly chips = FILTER_CHIPS;

  readonly scope = signal<'mine' | 'team' | 'all'>(this.defaultScopeForRole());

  readonly assigneeControl = new FormControl<string>('', { nonNullable: true });

  readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  readonly userMap = computed(() => {
    const map = new Map<string, string>();
    for (const u of this.users()) map.set(u.id, u.full_name);
    return map;
  });

  readonly canChangeScope = computed(() => {
    const role = this.auth.currentRoleName().toLowerCase();
    return role === 'owner' || role === 'admin' || role.includes('manager');
  });

  // --- Calendar derived signals ------------------------------------------

  readonly events = computed<CalendarEvent<Appointment>[]>(() => {
    const map = new Map<string, CalendarEvent<Appointment>>();
    for (const a of this.state.items()) {
      const d = new Date(a.scheduled_at);
      const key = this.dayKey(d);
      const existing = map.get(key);
      if (existing) {
        existing.count += 1;
        existing.items!.push(a);
      } else {
        map.set(key, { date: d, count: 1, items: [a] });
      }
    }
    return [...map.values()];
  });

  readonly daysAppointments = computed<Appointment[]>(() => {
    const day = this.selectedDay();
    return this.state
      .items()
      .filter((a) => isSameDay(new Date(a.scheduled_at), day))
      .sort((a, b) =>
        a.scheduled_at < b.scheduled_at ? -1 : a.scheduled_at > b.scheduled_at ? 1 : 0,
      );
  });

  readonly selectedDayLabel = computed(() => format(this.selectedDay(), 'EEEE, d MMMM yyyy'));

  // --- Selection + bulk --------------------------------------------------

  // --- Single-row actions (popover-driven) -------------------------------

  /** Appointment currently shown in the popover (`null` = closed). */
  readonly popoverAppointment = signal<Appointment | null>(null);

  /** Appointment being reassigned in the shared `ReassignModal`. */
  readonly singleReassignAppt = signal<Appointment | null>(null);
  readonly singleReassignSubmitting = signal(false);
  readonly singleReassignError = signal<string | null>(null);

  /** Appointment being rescheduled. */
  readonly rescheduleAppt = signal<Appointment | null>(null);
  readonly rescheduleSubmitting = signal(false);
  readonly rescheduleError = signal<string | null>(null);

  /** Appointment pending single-row cancel confirmation. */
  readonly cancelAppt = signal<Appointment | null>(null);
  readonly cancelSubmitting = signal(false);

  // --- URL state ---------------------------------------------------------

  readonly urlState: UrlFilterStateConfig = {
    view: {
      read: () => this.view(),
      write: (v) => {
        if (v === 'list' || v === 'calendar') this.view.set(v);
      },
      queryKey: 'view',
      defaultValue: 'list',
    },
    status: {
      read: () => this.statusFilter(),
      write: (v) => {
        if (
          v === 'all' ||
          v === 'upcoming' ||
          v === 'scheduled' ||
          v === 'completed' ||
          v === 'no_show' ||
          v === 'cancelled'
        ) {
          this.statusFilter.set(v);
        }
      },
      queryKey: 'status',
      defaultValue: 'all',
    },
    assignee: {
      read: () => this.assigneeControl.value,
      write: (v) => this.assigneeControl.setValue(v),
      queryKey: 'assignee',
    },
    scope: {
      read: () => this.scope(),
      write: (v) => {
        if (v === 'mine' || v === 'team' || v === 'all') this.scope.set(v);
      },
      queryKey: 'scope',
    },
    sort: {
      read: () => this.sortKey(),
      write: (v) => {
        if (v === 'scheduled_at' || v === 'created_at' || v === 'last_activity_at') {
          this.sortKey.set(v);
        }
      },
      queryKey: 'sort',
      defaultValue: 'scheduled_at',
    },
    order: {
      read: () => this.sortOrder(),
      write: (v) => {
        if (v === 'asc' || v === 'desc') this.sortOrder.set(v);
      },
      queryKey: 'order',
      defaultValue: 'asc',
    },
  };

  constructor() {
    this.state.bulkActions.set([
      {
        key: 'reassign',
        label: 'Reassign to…',
        icon: 'user-cog',
        permissionKey: 'appointments.reassign',
      },
      {
        key: 'cancel',
        label: 'Cancel',
        icon: 'x-circle',
        danger: true,
        permissionKey: 'appointments.write',
      },
    ]);
    effect(() => {
      // Track every filter signal so reload runs on any change.
      this.viewMonth();
      this.view();
      this.statusFilter();
      this.scope();
      this.sortKey();
      this.sortOrder();
      this.reload();
    });

    this.assigneeControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.reload());

    // Honour `/user/appointments?new=1` (dashboard quick-action) so
    // landing on the page from elsewhere opens the book-appointment
    // modal directly. Strip the param after consuming it.
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      if (params.get('new') !== null && !this.modalOpen()) {
        this.openBook();
        this.router.navigate([], {
          relativeTo: this.route,
          queryParams: { new: null },
          queryParamsHandling: 'merge',
          replaceUrl: true,
        });
      }
    });
  }

  // --- View / filter setters ---------------------------------------------

  protected setView(value: 'list' | 'calendar'): void {
    this.view.set(value);
  }

  protected setFilter(f: StatusFilter): void {
    this.statusFilter.set(f);
  }

  protected setScope(value: string): void {
    if (value !== 'mine' && value !== 'team' && value !== 'all') return;
    this.scope.set(value);
  }

  protected setSort(value: string): void {
    const [key, order] = value.split(':');
    if (key !== 'scheduled_at' && key !== 'created_at' && key !== 'last_activity_at') {
      return;
    }
    if (order !== 'asc' && order !== 'desc') return;
    this.sortKey.set(key);
    this.sortOrder.set(order);
  }

  protected onMonthChange(d: Date): void {
    this.viewMonth.set(d);
  }

  protected onDaySelected(d: Date): void {
    this.selectedDay.set(d);
  }

  protected openBook(): void {
    this.modalOpen.set(true);
  }

  protected closeBook(): void {
    this.modalOpen.set(false);
  }

  protected onAppointmentCreated(appt: Appointment): void {
    this.modalOpen.set(false);
    const at = new Date(appt.scheduled_at);
    this.viewMonth.set(at);
    this.selectedDay.set(at);
    this.reload();
  }

  protected conflictTitleFor = (id: string): string | null => {
    const a = this.state.items().find((x) => x.id === id);
    if (!a) return null;
    const time = format(new Date(a.scheduled_at), 'd MMM, HH:mm');
    return `${a.title} (${time})`;
  };

  // --- Selection ---------------------------------------------------------

  protected toggleRow(id: string, event: Event): void {
    event.stopPropagation();
    this.state.selectedIds.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  protected isSelected(id: string): boolean {
    return this.state.selectedIds().has(id);
  }

  protected clearSelection(): void {
    this.state.selectedIds.set(new Set());
  }

  // --- Bulk actions ------------------------------------------------------

  protected onBulkAction(key: string): void {
    this.state.bulkError.set(null);
    if (key === 'reassign') this.state.bulkModal.set('reassign');
    else if (key === 'cancel') this.state.bulkModal.set('cancel');
  }

  protected closeBulkModal(): void {
    this.state.bulkModal.set(null);
    this.state.bulkSubmitting.set(false);
    this.state.bulkError.set(null);
  }

  protected onBulkReassign(payload: ReassignConfirm): void {
    const ids = [...this.state.selectedIds()];
    if (ids.length === 0) return;
    if (!payload.userId) {
      this.state.bulkError.set('Appointments require an owner — pick a user.');
      return;
    }
    this.state.bulkSubmitting.set(true);
    this.state.bulkError.set(null);
    this.api
      .bulkReassign(ids, { userId: payload.userId, note: payload.note })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.state.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.state.bulkSubmitting.set(false);
          this.state.bulkError.set(extractApiError(err) ?? 'Could not reassign appointments.');
        },
      });
  }

  protected onBulkCancel(): void {
    const ids = [...this.state.selectedIds()];
    if (ids.length === 0) return;
    this.state.bulkSubmitting.set(true);
    this.state.bulkError.set(null);
    this.api
      .bulkCancel(ids)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.state.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          if (result.skipped > 0) {
            this.state.loadError.set(
              `${result.cancelled} cancelled; ${result.skipped} skipped (already cancelled / completed / no-show).`,
            );
          }
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.state.bulkSubmitting.set(false);
          this.state.bulkError.set(extractApiError(err) ?? 'Could not cancel appointments.');
        },
      });
  }

  // --- Popover -----------------------------------------------------------

  protected openPopover(appt: Appointment, event?: Event): void {
    event?.stopPropagation();
    this.popoverAppointment.set(appt);
  }

  protected closePopover(): void {
    this.popoverAppointment.set(null);
  }

  protected onPopoverReassign(): void {
    const a = this.popoverAppointment();
    if (!a) return;
    this.closePopover();
    this.singleReassignError.set(null);
    this.singleReassignAppt.set(a);
  }

  protected onPopoverReschedule(): void {
    const a = this.popoverAppointment();
    if (!a) return;
    this.closePopover();
    this.rescheduleError.set(null);
    this.rescheduleAppt.set(a);
  }

  protected onPopoverMarkCompleted(): void {
    const a = this.popoverAppointment();
    if (!a) return;
    this.closePopover();
    this.advanceStatus(a, 'completed');
  }

  protected onPopoverCancel(): void {
    const a = this.popoverAppointment();
    if (!a) return;
    this.closePopover();
    this.cancelAppt.set(a);
  }

  // --- Single-row reassign ----------------------------------------------

  protected closeSingleReassign(): void {
    this.singleReassignAppt.set(null);
    this.singleReassignSubmitting.set(false);
    this.singleReassignError.set(null);
  }

  protected onSingleReassign(payload: ReassignConfirm): void {
    const appt = this.singleReassignAppt();
    if (!appt) return;
    if (!payload.userId) {
      this.singleReassignError.set('Appointments require an owner — pick a user.');
      return;
    }
    this.singleReassignSubmitting.set(true);
    this.singleReassignError.set(null);
    this.api
      .reassign(appt.id, { userId: payload.userId, note: payload.note })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.singleReassignSubmitting.set(false);
          this.state.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.closeSingleReassign();
        },
        error: (err: HttpErrorResponse) => {
          this.singleReassignSubmitting.set(false);
          this.singleReassignError.set(extractApiError(err) ?? 'Could not reassign appointment.');
        },
      });
  }

  // --- Reschedule --------------------------------------------------------

  protected closeReschedule(): void {
    this.rescheduleAppt.set(null);
    this.rescheduleSubmitting.set(false);
    this.rescheduleError.set(null);
  }

  protected onRescheduleConfirm(payload: RescheduleConfirm): void {
    const appt = this.rescheduleAppt();
    if (!appt) return;
    this.rescheduleSubmitting.set(true);
    this.rescheduleError.set(null);
    this.api
      .reschedule(appt.id, {
        scheduledAt: payload.scheduledAt,
        reason: payload.reason,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.rescheduleSubmitting.set(false);
          this.state.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.closeReschedule();
        },
        error: (err: HttpErrorResponse) => {
          this.rescheduleSubmitting.set(false);
          this.rescheduleError.set(extractApiError(err) ?? 'Could not reschedule appointment.');
        },
      });
  }

  // --- Single-row cancel + status change --------------------------------

  protected closeCancelConfirm(): void {
    this.cancelAppt.set(null);
    this.cancelSubmitting.set(false);
  }

  protected onCancelConfirm(): void {
    const appt = this.cancelAppt();
    if (!appt) return;
    this.cancelSubmitting.set(true);
    this.api
      .update(appt.id, { status: 'cancelled' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.cancelSubmitting.set(false);
          this.state.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
          this.closeCancelConfirm();
        },
        error: (err: HttpErrorResponse) => {
          this.cancelSubmitting.set(false);
          this.closeCancelConfirm();
          this.state.loadError.set(extractApiError(err) ?? 'Could not cancel appointment.');
        },
      });
  }

  /** Inline status transition (e.g. Mark completed). Optimistic; reverts on error. */
  private advanceStatus(appt: Appointment, target: Appointment['status']): void {
    const before = this.state.items();
    this.state.items.update((rows) =>
      rows.map((r) => (r.id === appt.id ? { ...r, status: target } : r)),
    );
    this.api
      .update(appt.id, { status: target })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.state.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
        },
        error: (err: HttpErrorResponse) => {
          this.state.items.set(before);
          this.state.loadError.set(extractApiError(err) ?? 'Could not update appointment status.');
        },
      });
  }

  // --- Display helpers ---------------------------------------------------

  protected formatTime(iso: string): string {
    return format(new Date(iso), 'HH:mm');
  }

  protected formatDateTime(iso: string): string {
    return format(new Date(iso), 'd MMM yyyy, HH:mm');
  }

  protected contactName(id: string): string {
    return this.contactsById()[id]?.full_name ?? '—';
  }

  protected contactPhone(id: string): string | null {
    return this.contactsById()[id]?.phone ?? null;
  }

  protected contactEmail(id: string): string | null {
    return this.contactsById()[id]?.email ?? null;
  }

  protected ownerLabel(id: string | null): string {
    if (!id) return 'Unassigned';
    return this.userMap().get(id) ?? 'Unknown';
  }

  protected statusClass(status: Appointment['status']): string {
    switch (status) {
      case 'completed':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'cancelled':
        return 'bg-zinc-100 text-zinc-600 ring-zinc-200';
      case 'no_show':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      default:
        return 'bg-blue-100 text-blue-700 ring-blue-200';
    }
  }

  protected ownerPalette(userId: string | null): OwnerColor {
    return this.ownerColor(userId);
  }

  // --- Default scope-from-role ------------------------------------------

  private defaultScopeForRole(): 'mine' | 'team' | 'all' {
    const role = this.auth.currentRoleName();
    if (!role) return 'mine';
    const r = role.toLowerCase();
    if (r === 'owner' || r === 'admin') return 'all';
    if (r.includes('manager')) return 'team';
    return 'mine';
  }

  private resolveAssignee(): string | undefined {
    const raw = this.assigneeControl.value;
    if (!raw) {
      if (this.scope() === 'mine') {
        return this.auth.currentUserId() ?? undefined;
      }
      return undefined;
    }
    if (raw === 'me') return this.auth.currentUserId() ?? undefined;
    return raw;
  }

  private resolveStatusAndFrom(): {
    status?: AppointmentStatusValue;
    extraFrom?: string;
  } {
    const f = this.statusFilter();
    if (f === 'all') return {};
    if (f === 'upcoming') {
      return {
        status: 'scheduled',
        extraFrom: new Date().toISOString(),
      };
    }
    return { status: f };
  }

  private resolveDateWindow(extraFrom: string | undefined): {
    scheduledFrom?: string;
    scheduledTo?: string;
  } {
    if (this.view() === 'calendar') {
      const month = this.viewMonth();
      const fromDt = startOfWeek(startOfMonth(month), { weekStartsOn: 1 });
      const toDt = endOfWeek(endOfMonth(month), { weekStartsOn: 1 });
      const lower = extraFrom && new Date(extraFrom) > fromDt ? extraFrom : fromDt.toISOString();
      return { scheduledFrom: lower, scheduledTo: toDt.toISOString() };
    }
    return extraFrom ? { scheduledFrom: extraFrom } : {};
  }

  private reload(): void {
    const { status, extraFrom } = this.resolveStatusAndFrom();
    const { scheduledFrom, scheduledTo } = this.resolveDateWindow(extraFrom);

    this.state.loading.set(true);
    this.state.loadError.set(null);
    this.api
      .list({
        scheduledFrom,
        scheduledTo,
        assignedTo: this.resolveAssignee(),
        status,
        sort: this.sortKey(),
        order: this.sortOrder(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.state.items.set(rows);
          this.state.loading.set(false);
          this.hydrateContacts(rows);
        },
        error: (err: HttpErrorResponse) => {
          this.state.items.set([]);
          this.state.loading.set(false);
          this.state.loadError.set(extractApiError(err) ?? 'Could not load appointments.');
        },
      });
  }

  private hydrateContacts(rows: Appointment[]): void {
    const ids = new Set(rows.map((r) => r.contact_id));
    const cache = this.contactsById();
    const missing = [...ids].filter((id) => !cache[id]);
    if (missing.length === 0) return;
    forkJoin(missing.map((id) => this.contactsApi.get(id).pipe(catchError(() => of(null)))))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((results) => {
        this.contactsById.update((current) => {
          const next = { ...current };
          for (const c of results) {
            if (c) {
              next[c.id] = {
                id: c.id,
                full_name: c.full_name,
                phone: c.phone,
                email: c.email,
              };
            }
          }
          return next;
        });
      });
  }

  private dayKey(d: Date): string {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }
}
