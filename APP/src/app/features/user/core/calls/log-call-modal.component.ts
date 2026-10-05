import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  HostListener,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';
import { extractApiError } from '@core/services/api-error.util';

import {
  ContactListItem,
  ContactListResponse,
  ContactsApiService,
} from '../contacts/contacts-api.service';
import { commonValidators } from '../shared/validators';
import { FormToastHelper } from '../shared/forms/form-toast.helper';
import { ConfirmDialogService } from '../shared/confirm-dialog/confirm-dialog.service';
import { MobileDateTimeComponent } from '../shared/forms/mobile-datetime.component';
import { MobileSelectComponent, MobileSelectOption } from '../shared/forms/mobile-select.component';
import { Call, CallOutcome, CallsApiService } from './calls-api.service';

/**
 * Modal to log a phone call. Reused by:
 *   - Logs tab (admin types from scratch).
 *   - Phone Book tab (click-to-call pre-fills `contact_id` + phone).
 *
 * `outcomes` is passed in by the parent (loaded once and shared) so we
 * don't refetch on every modal open.
 */
/** Per-file limit (matches backend `_MAX_RECORDING_BYTES`). */
const MAX_RECORDING_MB = 30;
const ALLOWED_RECORDING_EXTS = ['.mp3', '.m4a', '.ogg', '.wav'] as const;
/** Calls are always logged after the fact — accept up to 30 days back. */
const CALL_BACKFILL_DAYS = 30;
/** 24 hours max (matches DB CHECK constraint on duration_sec). */
const MAX_CALL_DURATION_SEC = 24 * 60 * 60;

const recordingUploadValidator = commonValidators.fileUpload({
  maxMb: MAX_RECORDING_MB,
  exts: ALLOWED_RECORDING_EXTS,
});

@Component({
  selector: 'app-log-call-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    LucideAngularModule,
    MobileSelectComponent,
    MobileDateTimeComponent,
  ],
  templateUrl: './log-call-modal.component.html',
})
export class LogCallModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(CallsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly formToast = inject(FormToastHelper);
  private readonly confirmDialog = inject(ConfirmDialogService);
  /** True while the discard-changes confirm is up, so Esc doesn't stack. */
  private confirming = false;

  @Input() set outcomes(list: CallOutcome[]) {
    this._outcomes = list;
    this.form.controls.outcome_id.setValidators([commonValidators.picklist(list.map((o) => o.id))]);
    this.form.controls.outcome_id.updateValueAndValidity({ emitEvent: false });
  }
  get outcomes(): CallOutcome[] {
    return this._outcomes;
  }
  private _outcomes: CallOutcome[] = [];
  /** Pre-fill the contact id (used by Phone Book's click-to-call).
   *  Seeds the chip immediately with `prefilledContactName` (when
   *  supplied) so there is no empty-chip flash, then overlays the full
   *  contact record from the API so phone / email round out for the
   *  "Change → pick another" flow. */
  @Input() set prefilledContactId(value: string | null) {
    if (!value) return;
    this.form.patchValue({ contact_id: value });
    const seedName = this.prefilledContactName;
    if (seedName) {
      this.selectedContact.set({
        id: value,
        full_name: seedName,
        phone: null,
        email: null,
        source: null,
        tags: [],
        assigned_to_id: null,
        last_activity_at: null,
        created_at: new Date().toISOString(),
      } as unknown as ContactListItem);
    }
    this.contactsApi
      .get(value)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (c) =>
          this.selectedContact.set({
            id: c.id,
            full_name: c.full_name,
            phone: c.phone,
            email: c.email,
            source: c.source,
            tags: c.tags ?? [],
            assigned_to_id: c.assigned_to_id,
            last_activity_at: c.last_activity_at,
            created_at: c.created_at,
          } as ContactListItem),
        error: () => {
          /* leave whatever the seed painted; id is still on the form */
        },
      });
  }
  /** Optional display name from the caller — used only to paint the
   *  chip immediately so there's no flash while the full contact record
   *  loads. Phone Book supplies this from its already-in-hand row. */
  @Input() prefilledContactName: string | null = null;

  @Output() readonly saved = new EventEmitter<Call>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  /** Audio file the user selected (drag-drop or click-to-pick). Uploaded
   *  after the Call row is created so we have a stable id to attach to. */
  protected readonly recordingFile = signal<File | null>(null);
  protected readonly recordingError = signal<string | null>(null);
  protected readonly dragActive = signal(false);
  protected readonly uploadingRecording = signal(false);

  /** Non-null once `POST /calls` succeeds. If the follow-up recording
   *  upload then fails, we keep the modal open — the call row already
   *  exists so the rep can pick a different file and retry the upload
   *  without re-creating the call. `close()` propagates this to the
   *  parent so the list still refreshes on manual dismiss. */
  protected readonly createdCall = signal<Call | null>(null);

  // --- Contact picker state ------------------------------------------
  // Two-mode paginated picker:
  //   - Browse: fetch page 1 (50 rows) on modal open sorted by
  //     `last_activity_at desc` so the rep's recent conversations
  //     surface first. Infinite scroll on the dropdown loads the next
  //     page when the user scrolls near the bottom, up to the org's
  //     full contact count. No 200-row ceiling.
  //   - Search: 2+ chars kick a debounced API search — also paginated
  //     with the same scroll-to-load handler so orgs with lots of
  //     matches don't get truncated. Clearing the search input
  //     restores the browse list without re-fetching.
  //
  // The picked contact's id feeds `form.contact_id`; the chip shows
  // name/phone/email so a wrong pick is instantly visible.
  protected readonly selectedContact = signal<ContactListItem | null>(null);
  protected readonly contactSearch = signal('');
  protected readonly contactSearching = signal(false);
  protected readonly contactsLoading = signal(true);
  protected readonly contactsLoadingMore = signal(false);

  /** Rows per page for both browse and search paths. 10 keeps the
   *  inline dropdown short (only pushes the rest of the form down by
   *  the height of ~4 visible rows before internal scroll takes over)
   *  and matches the manager-locked "10 per page" ask. */
  private static readonly PAGE_SIZE = 10;

  // Browse-mode paging state.
  private readonly browseContacts = signal<ContactListItem[]>([]);
  private browsePage = 1;
  private browseTotal = 0;

  // Search-mode paging state — cleared each new search term.
  private readonly searchResults = signal<ContactListItem[]>([]);
  private searchPage = 1;
  private searchTotal = 0;
  private currentSearchTerm = '';

  /** What the template renders: search results when input has 2+ chars,
   *  otherwise the browse list. */
  protected readonly visibleContacts = computed<ContactListItem[]>(() =>
    this.contactSearch().trim().length >= 2 ? this.searchResults() : this.browseContacts(),
  );

  /** Whether the current mode has more rows the server can serve. Used
   *  by the scroll handler to short-circuit past the last page. */
  protected readonly hasMoreContacts = computed<boolean>(() => {
    if (this.contactSearch().trim().length >= 2) {
      return this.searchResults().length < this.searchTotal;
    }
    return this.browseContacts().length < this.browseTotal;
  });

  private readonly contactSearch$ = new Subject<string>();

  constructor() {
    // Debounced search subscription. Each new term resets to page 1;
    // subsequent pages for the same term are loaded via `loadMoreContacts`.
    this.contactSearch$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((q) => {
          const trimmed = q.trim();
          this.currentSearchTerm = trimmed;
          this.searchPage = 1;
          this.searchTotal = 0;
          this.searchResults.set([]);
          if (trimmed.length < 2) {
            this.contactSearching.set(false);
            return [{ items: [] as ContactListItem[], total: 0 } as ContactListResponse];
          }
          this.contactSearching.set(true);
          return this.contactsApi.list({
            q: trimmed,
            page: 1,
            size: LogCallModalComponent.PAGE_SIZE,
          });
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => {
          this.searchResults.set(resp.items);
          this.searchTotal = resp.total;
          this.contactSearching.set(false);
        },
        error: () => this.contactSearching.set(false),
      });

    // Kick page 1 of the browse list — silent on error, the search
    // fallback still works if the preload 500s or the network drops.
    this.contactsApi
      .list({
        page: 1,
        size: LogCallModalComponent.PAGE_SIZE,
        sort: 'last_activity_at',
        order: 'desc',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.browseContacts.set(resp.items);
          this.browseTotal = resp.total;
          this.contactsLoading.set(false);
        },
        error: () => this.contactsLoading.set(false),
      });
  }

  protected onContactSearchInput(event: Event): void {
    const v = (event.target as HTMLInputElement).value;
    this.contactSearch.set(v);
    this.contactSearch$.next(v);
  }

  /** Scroll-to-load handler bound to the results `<ul>`. Fires the
   *  next page when the operator has scrolled within `TRIGGER_PX` of
   *  the bottom. Guards against duplicate in-flight requests via
   *  `contactsLoadingMore` so a fast-scrolling user doesn't stack up
   *  four requests for the same page. */
  protected onContactsScroll(event: Event): void {
    if (this.contactsLoadingMore() || !this.hasMoreContacts()) return;
    const el = event.target as HTMLElement;
    const TRIGGER_PX = 40;
    if (el.scrollHeight - el.scrollTop - el.clientHeight > TRIGGER_PX) return;
    this.loadMoreContacts();
  }

  private loadMoreContacts(): void {
    const inSearch = this.contactSearch().trim().length >= 2;
    this.contactsLoadingMore.set(true);
    const query = inSearch
      ? {
          q: this.currentSearchTerm,
          page: this.searchPage + 1,
          size: LogCallModalComponent.PAGE_SIZE,
        }
      : {
          page: this.browsePage + 1,
          size: LogCallModalComponent.PAGE_SIZE,
          sort: 'last_activity_at' as const,
          order: 'desc' as const,
        };
    this.contactsApi
      .list(query)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          if (inSearch) {
            // Guard against a stale response arriving after the operator
            // typed a new search term — drop it silently in that case.
            if (this.currentSearchTerm !== query.q) return;
            this.searchResults.update((rows) => [...rows, ...resp.items]);
            this.searchPage += 1;
          } else {
            this.browseContacts.update((rows) => [...rows, ...resp.items]);
            this.browsePage += 1;
          }
          this.contactsLoadingMore.set(false);
        },
        error: () => this.contactsLoadingMore.set(false),
      });
  }

  protected pickContact(row: ContactListItem): void {
    this.selectedContact.set(row);
    this.form.controls.contact_id.setValue(row.id);
    this.searchResults.set([]);
    this.searchPage = 1;
    this.searchTotal = 0;
    this.contactSearch.set('');
  }

  protected clearContact(): void {
    this.selectedContact.set(null);
    this.form.controls.contact_id.setValue(null);
    this.contactSearch.set('');
    this.searchResults.set([]);
    this.searchPage = 1;
    this.searchTotal = 0;
  }

  protected readonly recordingSizeLabel = computed(() => {
    const f = this.recordingFile();
    if (!f) return '';
    const mb = f.size / (1024 * 1024);
    return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(f.size / 1024))} KB`;
  });

  protected readonly form = this.fb.group({
    contact_id: this.fb.control<string | null>(null),
    direction: this.fb.control<'in' | 'out'>('out', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    started_at: this.fb.control(this._nowIso(), {
      nonNullable: true,
      validators: [Validators.required, commonValidators.dateWithinPastDays(CALL_BACKFILL_DAYS)],
    }),
    duration_sec: this.fb.control(60, {
      nonNullable: true,
      validators: [Validators.required, Validators.min(0), Validators.max(MAX_CALL_DURATION_SEC)],
    }),
    outcome_id: this.fb.control<string | null>(null),
    notes: this.fb.control<string | null>(null, [commonValidators.maxLength(4000)]),
  });

  /** Direction options for the mobile picker. */
  protected readonly directionOptions: ReadonlyArray<MobileSelectOption> = [
    { value: 'out', label: 'Outgoing' },
    { value: 'in', label: 'Incoming' },
  ];

  /** Outcome options list — includes the `null` "— Not set —"
   *  placeholder as an empty-string entry the mobile picker can handle
   *  (converted back to `null` in `onOutcomePicked`). */
  protected outcomeOptions(): ReadonlyArray<MobileSelectOption> {
    const opts: MobileSelectOption[] = [{ value: '', label: '— Not set —' }];
    for (const o of this._outcomes) opts.push({ value: o.id, label: o.label });
    return opts;
  }

  /** Value-only variants for `<crm-mobile-select>`. */
  protected onDirectionPicked(value: string): void {
    this.form.controls.direction.setValue(value as 'in' | 'out');
  }

  protected onOutcomePicked(value: string): void {
    this.form.controls.outcome_id.setValue(value || null);
  }

  /** Handler for `<crm-mobile-datetime>` — value is `YYYY-MM-DDTHH:mm`
   *  (same shape as the native input) so the form control's downstream
   *  `new Date(v.started_at).toISOString()` conversion still works. */
  protected onStartedAtPicked(value: string): void {
    this.form.controls.started_at.setValue(value);
  }

  /** ISO-local string for "30 days ago at 00:00" — the earliest slot
   *  the picker should offer as a `min` boundary. Matches the
   *  `dateWithinPastDays(CALL_BACKFILL_DAYS)` validator so the picker
   *  can't offer a value the validator will reject. */
  protected readonly minStartedAt = (() => {
    const d = new Date();
    d.setDate(d.getDate() - CALL_BACKFILL_DAYS);
    d.setHours(0, 0, 0, 0);
    const p = (n: number): string => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(
      d.getMinutes(),
    )}`;
  })();

  /** ISO-local string for "now" — the latest slot the picker should
   *  offer. Recomputed lazily via a getter so it's fresh each open. */
  protected get maxStartedAt(): string {
    const d = new Date();
    const p = (n: number): string => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(
      d.getMinutes(),
    )}`;
  }

  protected save(): void {
    // Post-create retry path: call already exists, only the recording
    // upload failed. Skip re-POST /calls and just retry the upload.
    const existing = this.createdCall();
    if (existing !== null) {
      this.afterCreate(existing);
      return;
    }
    if (!this.form.valid) {
      this.form.markAllAsTouched();
      this.formToast.requiredFieldsMissing();
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);
    const v = this.form.getRawValue();
    this.api
      .createCall({
        contact_id: v.contact_id ?? null,
        direction: v.direction,
        started_at: new Date(v.started_at).toISOString(),
        duration_sec: v.duration_sec,
        outcome_id: v.outcome_id ?? null,
        notes: v.notes ?? null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (call) => {
          this.createdCall.set(call);
          this.afterCreate(call);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not log call.');
        },
      });
  }

  /** After the Call row lands, upload the recording (if any) then
   *  emit `saved`. The recording is a follow-up POST because the
   *  create endpoint takes JSON — we don't try to shove the audio
   *  through the same body. */
  private afterCreate(call: Call): void {
    const file = this.recordingFile();
    if (!file) {
      this.submitting.set(false);
      this.saved.emit(call);
      return;
    }
    this.uploadingRecording.set(true);
    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .uploadRecording(call.id, file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.uploadingRecording.set(false);
          this.submitting.set(false);
          this.saved.emit(updated);
        },
        error: (err: HttpErrorResponse) => {
          this.uploadingRecording.set(false);
          this.submitting.set(false);
          // The Call row exists; recording failed. Keep the modal open
          // so the rep can see the error, swap the file, and retry
          // the upload — there is no separate "edit call" flow to fall
          // back to. `close()` still emits `saved` so the parent's
          // list refreshes if the rep gives up and dismisses the modal.
          this.submitError.set(
            extractApiError(err) ?? 'Recording upload failed. Try a different file or dismiss.',
          );
        },
      });
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (!this.confirming) void this.close();
  }

  /** Cancel / Esc. Asks before throwing away what was typed. */
  protected async close(): Promise<void> {
    if (this.submitting()) return;
    // If the call already landed but the recording upload didn't,
    // treat close as a "give up on the recording" — emit saved so the
    // parent list picks up the new call row instead of leaving it
    // stranded (invisible to the operator until a manual refresh).
    const existing = this.createdCall();
    if (existing !== null) {
      this.saved.emit(existing);
      return;
    }
    if (this.form.dirty || this.recordingFile() !== null) {
      this.confirming = true;
      try {
        const ok = await this.confirmDialog.ask({
          title: 'Discard this call log?',
          body: 'The details you entered will be lost.',
          confirmLabel: 'Discard',
          danger: true,
        });
        if (!ok) return;
      } finally {
        this.confirming = false;
      }
    }
    this.cancel.emit();
  }

  // --- Recording file picking -----------------------------------------

  protected onRecordingPicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) this.acceptRecording(file);
    // Reset so re-selecting the same file still fires change.
    input.value = '';
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(true);
  }

  protected onDragLeave(): void {
    this.dragActive.set(false);
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) this.acceptRecording(file);
  }

  protected clearRecording(): void {
    this.recordingFile.set(null);
    this.recordingError.set(null);
  }

  private acceptRecording(file: File): void {
    this.recordingError.set(null);
    const errors = recordingUploadValidator(new FormControl(file));
    if (errors?.['unsupportedFileType']) {
      this.recordingError.set(
        `Unsupported format. Allowed: ${ALLOWED_RECORDING_EXTS.join(', ')} (mp4/video is not accepted).`,
      );
      return;
    }
    if (errors?.['fileTooLarge']) {
      const mb = Math.round(file.size / (1024 * 1024));
      this.recordingError.set(
        `File is ${mb} MB — maximum is ${MAX_RECORDING_MB} MB. Try M4A instead of WAV.`,
      );
      return;
    }
    this.recordingFile.set(file);
  }

  private _nowIso(): string {
    // datetime-local input wants `YYYY-MM-DDTHH:mm` (no seconds, no TZ)
    const d = new Date();
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
}
