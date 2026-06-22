import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  BusinessHoursDay,
  BusinessHoursInterval,
  WhatsAppBusinessProfile,
  WhatsAppBusinessProfileApiService,
  WhatsAppBusinessProfilePatch,
  WhatsAppBusinessVertical,
} from './whatsapp-business-profile-api.service';

/**
 * WhatsApp Business profile editor
 * (whatsapp-platform-upgrade Step 11).
 *
 * Single-page editor for the Meta business profile (about /
 * description / address / email / websites / vertical / picture)
 * plus the Core-CRM-only fields Step 16 reads (business hours,
 * greeting message, away message).
 *
 * Save dispatches a PATCH containing only the changed fields so the
 * Meta-side update doesn't burn quota on untouched values (Meta caps
 * profile updates at ~10/day per phone).
 */

const VERTICALS: WhatsAppBusinessVertical[] = [
  'UNDEFINED',
  'OTHER',
  'AUTO',
  'BEAUTY',
  'APPAREL',
  'EDU',
  'ENTERTAIN',
  'EVENT_PLAN',
  'FINANCE',
  'GROCERY',
  'GOVT',
  'HOTEL',
  'HEALTH',
  'NONPROFIT',
  'PROF_SERVICES',
  'RETAIL',
  'TRAVEL',
  'RESTAURANT',
];

const DAY_LABELS = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
];

const DEFAULT_HOURS: BusinessHoursDay[] = [0, 1, 2, 3, 4, 5].map((d) => ({
  day: d,
  intervals: [{ open: '10:00', close: '19:00' }],
}));


@Component({
  selector: 'app-whatsapp-business-profile-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  templateUrl: './business-profile.page.html',
})
export class WhatsAppBusinessProfilePageComponent {
  private readonly api = inject(WhatsAppBusinessProfileApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly VERTICALS = VERTICALS;
  protected readonly DAY_LABELS = DAY_LABELS;

  @ViewChild('photoInput') protected photoInput?: ElementRef<HTMLInputElement>;

  protected readonly loading = signal<boolean>(false);
  protected readonly saving = signal<boolean>(false);
  protected readonly uploadingPhoto = signal<boolean>(false);
  protected readonly refreshing = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);

  protected readonly profile = signal<WhatsAppBusinessProfile | null>(null);

  // Editable mirrors — operator-edited locally; only the diff is
  // PATCHed on save. Cleared & re-hydrated from `profile` on every
  // server-side response.
  protected readonly about = signal('');
  protected readonly description = signal('');
  protected readonly address = signal('');
  protected readonly email = signal('');
  protected readonly websites = signal<string[]>([]);
  protected readonly vertical = signal<WhatsAppBusinessVertical>('UNDEFINED');
  protected readonly hours = signal<BusinessHoursDay[]>(DEFAULT_HOURS);
  protected readonly greetingMessage = signal('');
  protected readonly awayMessage = signal('');

  /** True when the editable mirrors differ from the last server-side
   *  profile — drives the "Unsaved changes" indicator + Save button
   *  enabled-state. */
  protected readonly dirty = computed(() => {
    const p = this.profile();
    if (!p) return false;
    return (
      (p.about || '') !== this.about() ||
      (p.description || '') !== this.description() ||
      (p.address || '') !== this.address() ||
      (p.email || '') !== this.email() ||
      JSON.stringify(p.websites) !== JSON.stringify(this.websites()) ||
      (p.vertical || 'UNDEFINED') !== this.vertical() ||
      JSON.stringify(p.business_hours) !== JSON.stringify(this.hours()) ||
      (p.greeting_message || '') !== this.greetingMessage() ||
      (p.away_message || '') !== this.awayMessage()
    );
  });

  constructor() {
    this.load();
  }

  // --- load -------------------------------------------------------

  protected load(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .get()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (p) => {
          this.profile.set(p);
          this.hydrate(p);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.profile.set(null);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ??
              'Could not load WhatsApp business profile.',
          );
        },
      });
  }

  private hydrate(p: WhatsAppBusinessProfile): void {
    this.about.set(p.about || '');
    this.description.set(p.description || '');
    this.address.set(p.address || '');
    this.email.set(p.email || '');
    this.websites.set([...p.websites]);
    this.vertical.set(
      (p.vertical as WhatsAppBusinessVertical) || 'UNDEFINED',
    );
    this.hours.set(
      p.business_hours.length > 0 ? this.cloneHours(p.business_hours) : DEFAULT_HOURS,
    );
    this.greetingMessage.set(p.greeting_message || '');
    this.awayMessage.set(p.away_message || '');
  }

  private cloneHours(hours: BusinessHoursDay[]): BusinessHoursDay[] {
    return hours.map((h) => ({
      day: h.day,
      intervals: h.intervals.map((i) => ({ open: i.open, close: i.close })),
    }));
  }

  // --- save -------------------------------------------------------

  protected save(): void {
    if (!this.dirty() || this.saving()) return;
    const p = this.profile();
    if (!p) return;

    const patch: WhatsAppBusinessProfilePatch = {};
    if ((p.about || '') !== this.about()) patch.about = this.about();
    if ((p.description || '') !== this.description()) patch.description = this.description();
    if ((p.address || '') !== this.address()) patch.address = this.address();
    if ((p.email || '') !== this.email()) patch.email = this.email();
    if (JSON.stringify(p.websites) !== JSON.stringify(this.websites())) {
      patch.websites = this.websites().filter((w) => w.trim().length > 0);
    }
    if ((p.vertical || 'UNDEFINED') !== this.vertical()) patch.vertical = this.vertical();
    if (JSON.stringify(p.business_hours) !== JSON.stringify(this.hours())) {
      patch.business_hours = this.hours();
    }
    if ((p.greeting_message || '') !== this.greetingMessage()) {
      patch.greeting_message = this.greetingMessage();
    }
    if ((p.away_message || '') !== this.awayMessage()) {
      patch.away_message = this.awayMessage();
    }

    this.saving.set(true);
    this.toast.set(null);
    this.api
      .patch(patch)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.profile.set(updated);
          this.hydrate(updated);
          this.saving.set(false);
          this.toast.set('Profile saved.');
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.toast.set(
            extractApiError(err) ?? 'Could not save the profile.',
          );
        },
      });
  }

  protected refreshFromMeta(): void {
    this.refreshing.set(true);
    this.toast.set(null);
    this.api
      .refresh()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.profile.set(updated);
          this.hydrate(updated);
          this.refreshing.set(false);
          this.toast.set('Synced from Meta.');
        },
        error: (err: HttpErrorResponse) => {
          this.refreshing.set(false);
          this.toast.set(
            extractApiError(err) ?? 'Could not refresh from Meta.',
          );
        },
      });
  }

  // --- websites ---------------------------------------------------

  protected addWebsite(): void {
    if (this.websites().length >= 2) return;
    this.websites.update((arr) => [...arr, '']);
  }

  protected updateWebsite(idx: number, value: string): void {
    this.websites.update((arr) =>
      arr.map((v, i) => (i === idx ? value : v)),
    );
  }

  protected removeWebsite(idx: number): void {
    this.websites.update((arr) => arr.filter((_, i) => i !== idx));
  }

  // --- hours ------------------------------------------------------

  protected dayLabel(day: number): string {
    return DAY_LABELS[day] ?? `Day ${day}`;
  }

  protected isDayOpen(day: number): boolean {
    return this.hours().some((h) => h.day === day && h.intervals.length > 0);
  }

  protected toggleDay(day: number): void {
    if (this.isDayOpen(day)) {
      this.hours.update((arr) => arr.filter((h) => h.day !== day));
    } else {
      this.hours.update((arr) => [
        ...arr,
        { day, intervals: [{ open: '10:00', close: '19:00' }] },
      ]);
    }
  }

  protected intervalsForDay(day: number): BusinessHoursInterval[] {
    return this.hours().find((h) => h.day === day)?.intervals ?? [];
  }

  protected addInterval(day: number): void {
    this.hours.update((arr) =>
      arr.map((h) =>
        h.day === day
          ? {
              ...h,
              intervals: [...h.intervals, { open: '14:00', close: '18:00' }],
            }
          : h,
      ),
    );
  }

  protected updateInterval(
    day: number,
    idx: number,
    patch: Partial<BusinessHoursInterval>,
  ): void {
    this.hours.update((arr) =>
      arr.map((h) =>
        h.day === day
          ? {
              ...h,
              intervals: h.intervals.map((iv, i) =>
                i === idx ? { ...iv, ...patch } : iv,
              ),
            }
          : h,
      ),
    );
  }

  protected removeInterval(day: number, idx: number): void {
    this.hours.update((arr) =>
      arr.map((h) =>
        h.day === day
          ? { ...h, intervals: h.intervals.filter((_, i) => i !== idx) }
          : h,
      ),
    );
  }

  /** Copy Monday's intervals to Tue-Sat (weekday only). Common
   *  retail pattern: open Mon-Sat, closed Sunday. */
  protected copyMondayToWeekdays(): void {
    const monday = this.hours().find((h) => h.day === 0);
    if (!monday) return;
    const cloned = monday.intervals.map((i) => ({
      open: i.open,
      close: i.close,
    }));
    this.hours.update((arr) => {
      const filtered = arr.filter((h) => h.day === 0 || h.day === 6);
      for (const day of [1, 2, 3, 4, 5]) {
        filtered.push({ day, intervals: [...cloned] });
      }
      return filtered.sort((a, b) => a.day - b.day);
    });
  }

  // --- photo ------------------------------------------------------

  protected openPhotoPicker(): void {
    this.photoInput?.nativeElement.click();
  }

  protected onPhotoPicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    input.value = ''; // allow re-picking the same file
    if (!file) return;
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      this.toast.set('Profile picture must be JPEG or PNG.');
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      this.toast.set('Profile picture must be 5 MB or smaller.');
      return;
    }
    this.uploadingPhoto.set(true);
    this.toast.set(null);
    this.api
      .uploadPicture(file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.profile.set(updated);
          this.hydrate(updated);
          this.uploadingPhoto.set(false);
          this.toast.set('Profile picture updated.');
        },
        error: (err: HttpErrorResponse) => {
          this.uploadingPhoto.set(false);
          this.toast.set(
            extractApiError(err) ?? 'Could not upload the picture.',
          );
        },
      });
  }

  protected dismissToast(): void {
    this.toast.set(null);
  }

  // --- variable inserters -----------------------------------------

  protected insertGreetingVar(variable: string): void {
    this.greetingMessage.update((v) => `${v}{{${variable}}}`);
  }

  protected insertAwayVar(variable: string): void {
    this.awayMessage.update((v) => `${v}{{${variable}}}`);
  }
}
