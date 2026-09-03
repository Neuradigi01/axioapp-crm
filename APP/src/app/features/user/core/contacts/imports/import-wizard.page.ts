import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { MobileSelectComponent } from '../../shared/forms/mobile-select.component';
import {
  ContactFieldTarget,
  ContactImportCommitOut,
  ContactImportDryRunOut,
  ContactImportUploadOut,
  ContactsApiService,
  WhatsAppOptInSource,
} from '../contacts-api.service';
import { BulkImportOptInStepComponent } from './opt-in-step.component';

/**
 * `/user/contacts/import` — 3-step bulk import wizard wired to the
 * Step 3.5.10 backend.
 *
 *   Step 1 (upload):  drop / pick a .xlsx or .csv → POST /upload
 *                     gives the import id + suggested mapping.
 *   Step 2 (map):     each detected column gets a dropdown to a
 *                     ContactFieldTarget; suggested mapping pre-fills.
 *                     Optional "create group from this import" toggle.
 *                     Continue → POST /{id}/dry-run.
 *   Step 3 (preview): dry-run counts + collapsible error table.
 *                     Commit → POST /{id}/commit, then renders the
 *                     success state with "Back to contacts" / "Open
 *                     group" CTAs (no toast service in the app today).
 *
 * Per the step's pre-impl question (b), file drops do NOT auto-upload —
 * the operator confirms with a Continue button so accidental drops
 * don't waste a backend parse.
 */

interface FieldTargetOption {
  value: ContactFieldTarget;
  label: string;
}

const STANDARD_FIELD_TARGETS: FieldTargetOption[] = [
  { value: 'skip', label: 'Skip this column' },
  { value: 'full_name', label: 'Full name' },
  { value: 'phone', label: 'Phone' },
  { value: 'email', label: 'Email' },
  { value: 'source', label: 'Source' },
  { value: 'tag', label: 'Tag' },
];

const ACCEPT_EXTENSIONS = ['.xlsx', '.csv'] as const;

/** Errors past this count get hidden behind an "expand" toggle so an
 * import with 5000 row errors doesn't melt the browser. */
const ERROR_VISIBLE_LIMIT = 50;

@Component({
  selector: 'app-contact-import-wizard-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule, BulkImportOptInStepComponent, MobileSelectComponent],
  templateUrl: './import-wizard.page.html',
})
export class ContactImportWizardPageComponent implements OnInit {
  /** Step 22 — DPDP opt-in provenance picked on the map step.
   *  Null until the operator picks one; gates the Continue button. */
  protected readonly optInSource = signal<WhatsAppOptInSource | null>(null);

  protected setOptInSource(source: WhatsAppOptInSource): void {
    this.optInSource.set(source);
  }

  private readonly api = inject(ContactsApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  /** Custom-field targets for entity ``contact`` in this org — loaded
   *  once on init from ``GET /custom-fields/contact/render`` and
   *  concatenated onto the standard targets so the mapping dropdown
   *  surfaces them alongside Full name / Phone / etc. Empty until
   *  the render call returns; the dropdown works fine in that
   *  window with just the standard targets. */
  protected readonly customFieldTargets = signal<FieldTargetOption[]>([]);

  protected readonly fieldTargets = computed<FieldTargetOption[]>(() => [
    ...STANDARD_FIELD_TARGETS,
    ...this.customFieldTargets(),
  ]);

  /** Set of every currently-legal target value. Used to coerce the
   *  backend's suggested mapping on upload — an unknown or stale
   *  target snaps to ``'skip'`` so the dropdown never shows a value
   *  it can't render. Recomputes when custom fields load. */
  protected readonly validTargetSet = computed<Set<ContactFieldTarget>>(
    () => new Set(this.fieldTargets().map((t) => t.value)),
  );

  protected readonly errorVisibleLimit = ERROR_VISIBLE_LIMIT;

  ngOnInit(): void {
    this.api
      .renderFields()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (defs) => {
          this.customFieldTargets.set(
            defs.map((f) => ({
              value: `custom_data.${f.field_key}` as ContactFieldTarget,
              label: `Custom · ${f.field_label}`,
            })),
          );
        },
        // Silent: if the render call hiccups the wizard still works
        // with just the six standard targets — losing the custom
        // fields is a degrade, not a blocker.
        error: () => undefined,
      });
  }

  /** 1=upload · 2=map · 3=preview · 4=success card. */
  protected readonly step = signal<1 | 2 | 3 | 4>(1);

  // --- Step 1 ---------------------------------------------------------
  protected readonly selectedFile = signal<File | null>(null);
  protected readonly dragOver = signal(false);
  protected readonly uploading = signal(false);
  protected readonly uploadError = signal<string | null>(null);

  // --- Cross-step state ----------------------------------------------
  protected readonly importMeta = signal<ContactImportUploadOut | null>(null);

  // --- Step 2 ---------------------------------------------------------
  /** Column name → contact field target. Initialised from the backend's
   * suggested mapping. */
  protected readonly mapping = signal<Record<string, ContactFieldTarget>>({});
  protected readonly createGroup = signal(false);
  protected readonly groupName = signal('');

  // --- Step 3 ---------------------------------------------------------
  protected readonly dryRunRunning = signal(false);
  protected readonly dryRunError = signal<string | null>(null);
  protected readonly dryRunResult = signal<ContactImportDryRunOut | null>(null);
  protected readonly errorsExpanded = signal(false);

  protected readonly committing = signal(false);
  protected readonly commitError = signal<string | null>(null);
  protected readonly commitResult = signal<ContactImportCommitOut | null>(null);

  // Async pivot (2026-07-30) — polling state for the processing screen.
  protected readonly cancelling = signal(false);
  protected readonly cancelError = signal<string | null>(null);
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  /** Set true by `stopPolling()` — the poll callbacks check this before
   *  scheduling the next tick so a late HTTP error can't resurrect the
   *  loop after the component has been destroyed / navigated away. */
  private pollingCancelled = false;

  protected readonly isProcessing = computed(() => {
    const r = this.commitResult();
    return r !== null && r.status === 'processing';
  });

  protected readonly isFailed = computed(() => {
    const r = this.commitResult();
    return r !== null && r.status === 'failed';
  });

  protected readonly isCancelled = computed(() => {
    const r = this.commitResult();
    return r !== null && r.status === 'cancelled';
  });

  // errors.csv download state
  protected readonly downloadingErrors = signal(false);
  protected readonly downloadErrorsMsg = signal<string | null>(null);

  // skipped.csv download state (3-CSV parity with leads).
  protected readonly downloadingSkipped = signal(false);
  protected readonly downloadSkippedMsg = signal<string | null>(null);

  // warnings.csv download state (3-CSV parity with leads).
  protected readonly downloadingWarnings = signal(false);
  protected readonly downloadWarningsMsg = signal<string | null>(null);

  // --- Derived --------------------------------------------------------

  protected readonly fileSizeLabel = computed(() => {
    const f = this.selectedFile();
    return f ? this.formatBytes(f.size) : null;
  });

  protected readonly fullNameMapped = computed(() =>
    Object.values(this.mapping()).includes('full_name'),
  );

  /** Same target picked by 2+ columns — flag the columns so the
   * operator can pick a different mapping or skip one. */
  protected readonly duplicateTargets = computed(() => {
    const counts: Record<string, number> = {};
    for (const v of Object.values(this.mapping())) {
      if (v === 'skip') continue;
      counts[v] = (counts[v] ?? 0) + 1;
    }
    return new Set(
      Object.entries(counts)
        .filter(([, n]) => n > 1)
        .map(([k]) => k),
    );
  });

  protected readonly groupNameRequired = computed(
    () => this.createGroup() && this.groupName().trim().length === 0,
  );

  protected readonly canRunDryRun = computed(
    () =>
      this.fullNameMapped() &&
      this.duplicateTargets().size === 0 &&
      !this.groupNameRequired() &&
      this.optInSource() !== null &&
      !this.dryRunRunning(),
  );

  protected readonly canCommit = computed(() => {
    const dr = this.dryRunResult();
    return dr !== null && dr.will_insert > 0 && !this.committing() && !this.groupNameRequired();
  });

  protected readonly visibleErrors = computed(() => {
    const errs = this.dryRunResult()?.errors ?? [];
    return this.errorsExpanded() ? errs : errs.slice(0, ERROR_VISIBLE_LIMIT);
  });

  protected readonly duplicatesExpanded = signal(false);
  protected readonly warningsExpanded = signal(false);

  protected readonly visibleDuplicates = computed(() => {
    const rows = this.dryRunResult()?.duplicates ?? [];
    return this.duplicatesExpanded() ? rows : rows.slice(0, ERROR_VISIBLE_LIMIT);
  });

  protected readonly visibleWarnings = computed(() => {
    const rows = this.dryRunResult()?.warnings ?? [];
    return this.warningsExpanded() ? rows : rows.slice(0, ERROR_VISIBLE_LIMIT);
  });

  protected toggleDuplicatesExpanded(): void {
    this.duplicatesExpanded.update((v) => !v);
  }

  protected toggleWarningsExpanded(): void {
    this.warningsExpanded.update((v) => !v);
  }

  // --- Step 1 handlers ------------------------------------------------

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(true);
  }

  protected onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(false);
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(false);
    const file = event.dataTransfer?.files?.[0] ?? null;
    this.setFile(file);
  }

  protected onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    this.setFile(file);
    // Reset the input so picking the same file twice still fires change.
    input.value = '';
  }

  protected clearFile(): void {
    this.selectedFile.set(null);
    this.uploadError.set(null);
  }

  protected submitUpload(): void {
    const file = this.selectedFile();
    if (!file || this.uploading()) return;
    this.uploading.set(true);
    this.uploadError.set(null);
    this.api
      .uploadImport(file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (meta) => {
          this.uploading.set(false);
          this.importMeta.set(meta);
          // Seed the mapping with the backend's suggestion; coerce any
          // unknown target value to "skip" so a stale backend can't
          // smuggle in a target the dropdown doesn't render.
          const safe: Record<string, ContactFieldTarget> = {};
          for (const col of meta.headers) {
            const guess = meta.suggested_mapping[col];
            safe[col] = this.validTargetSet().has(guess) ? guess : 'skip';
          }
          this.mapping.set(safe);
          this.step.set(2);
        },
        error: (err: HttpErrorResponse) => {
          this.uploading.set(false);
          this.uploadError.set(
            extractApiError(err) ?? 'Upload failed — please try again or check the file format.',
          );
        },
      });
  }

  private setFile(file: File | null): void {
    if (!file) {
      this.selectedFile.set(null);
      return;
    }
    const lower = file.name.toLowerCase();
    const ok = ACCEPT_EXTENSIONS.some((ext) => lower.endsWith(ext));
    if (!ok) {
      this.uploadError.set('Only .xlsx and .csv files are accepted.');
      this.selectedFile.set(null);
      return;
    }
    this.uploadError.set(null);
    this.selectedFile.set(file);
  }

  // --- Step 2 handlers ------------------------------------------------

  protected onMappingChange(column: string, event: Event): void {
    const value = (event.target as HTMLSelectElement).value as ContactFieldTarget;
    this.mapping.update((m) => ({ ...m, [column]: value }));
  }

  /** Overload for `<crm-mobile-select>` which emits the string value
   *  directly (no wrapping Event object). */
  protected onMappingValue(column: string, value: string): void {
    this.mapping.update((m) => ({ ...m, [column]: value as ContactFieldTarget }));
  }

  protected onCreateGroupChange(event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    this.createGroup.set(checked);
    if (!checked) this.groupName.set('');
  }

  protected onGroupNameInput(event: Event): void {
    this.groupName.set((event.target as HTMLInputElement).value);
  }

  protected backToUpload(): void {
    // Keep the file so the operator can simply re-upload if they
    // realise they want to swap files.
    this.step.set(1);
  }

  protected runDryRun(): void {
    const meta = this.importMeta();
    if (!meta || !this.canRunDryRun()) return;
    this.dryRunRunning.set(true);
    this.dryRunError.set(null);
    this.dryRunResult.set(null);
    this.errorsExpanded.set(false);
    this.duplicatesExpanded.set(false);
    this.warningsExpanded.set(false);
    this.api
      .dryRunImport(meta.id, this.buildRunBody())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.dryRunRunning.set(false);
          this.dryRunResult.set(result);
          this.step.set(3);
        },
        error: (err: HttpErrorResponse) => {
          this.dryRunRunning.set(false);
          this.dryRunError.set(extractApiError(err) ?? 'Could not preview the import.');
        },
      });
  }

  // --- Step 3 handlers ------------------------------------------------

  protected backToMapping(): void {
    this.step.set(2);
  }

  protected toggleErrorsExpanded(): void {
    this.errorsExpanded.update((v) => !v);
  }

  protected commit(): void {
    const meta = this.importMeta();
    if (!meta || !this.canCommit()) return;
    this.committing.set(true);
    this.commitError.set(null);
    this.cancelError.set(null);
    this.api
      .commitImport(meta.id, this.buildRunBody())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          // Async pivot (2026-07-30): backend may return `status='processing'`
          // when the Celery worker is queued but hasn't finished. Show a
          // processing screen and poll until terminal, then show success.
          this.commitResult.set(result);
          if (this.isTerminalStatus(result.status)) {
            this.committing.set(false);
            this.step.set(4);
          } else {
            this.step.set(4);
            this.startPolling(meta.id);
          }
        },
        error: (err: HttpErrorResponse) => {
          this.committing.set(false);
          this.commitError.set(extractApiError(err) ?? 'Could not commit the import.');
        },
      });
  }

  /** Download the per-row errors as a CSV file. Available on the
   *  preview step (after dry-run) and the success step (after commit)
   *  whenever the import produced at least one error. */
  protected downloadErrors(): void {
    const meta = this.importMeta();
    if (!meta || this.downloadingErrors()) return;
    this.downloadingErrors.set(true);
    this.downloadErrorsMsg.set(null);
    this.api
      .downloadImportErrors(meta.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.downloadingErrors.set(false);
          this.triggerBlobDownload(blob, `contact-import-${meta.id}-errors.csv`);
        },
        error: (err: HttpErrorResponse) => {
          this.downloadingErrors.set(false);
          this.downloadErrorsMsg.set(extractApiError(err) ?? 'Could not download the errors CSV.');
        },
      });
  }

  /** Download the per-row skipped-duplicates CSV. Same shape as the
   *  errors CSV; only populated for rows that collapsed onto an
   *  existing contact on the phone dedup key. */
  protected downloadSkipped(): void {
    const meta = this.importMeta();
    if (!meta || this.downloadingSkipped()) return;
    this.downloadingSkipped.set(true);
    this.downloadSkippedMsg.set(null);
    this.api
      .downloadImportSkipped(meta.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.downloadingSkipped.set(false);
          this.triggerBlobDownload(blob, `contact-import-${meta.id}-skipped.csv`);
        },
        error: (err: HttpErrorResponse) => {
          this.downloadingSkipped.set(false);
          this.downloadSkippedMsg.set(
            extractApiError(err) ?? 'Could not download the duplicates CSV.',
          );
        },
      });
  }

  /** Download the per-row warnings CSV — rows that imported but had a
   *  value coerced (e.g. tag truncated to 64 chars). */
  protected downloadWarnings(): void {
    const meta = this.importMeta();
    if (!meta || this.downloadingWarnings()) return;
    this.downloadingWarnings.set(true);
    this.downloadWarningsMsg.set(null);
    this.api
      .downloadImportWarnings(meta.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.downloadingWarnings.set(false);
          this.triggerBlobDownload(blob, `contact-import-${meta.id}-warnings.csv`);
        },
        error: (err: HttpErrorResponse) => {
          this.downloadingWarnings.set(false);
          this.downloadWarningsMsg.set(
            extractApiError(err) ?? 'Could not download the warnings CSV.',
          );
        },
      });
  }

  /** Terminal statuses stop the poll loop and unfreeze the UI. */
  private isTerminalStatus(status: string): boolean {
    return status === 'committed' || status === 'failed' || status === 'cancelled';
  }

  /** Start polling the import row until it reaches a terminal status.
   *  Backs off gently — 1s for the first 10 polls, 2s afterwards —
   *  so a fast dev commit clears in ~1s and a big prod commit doesn't
   *  hammer the API. Polling stops on component destroy via the
   *  ``destroyRef`` cleanup. */
  private startPolling(importId: string): void {
    this.stopPolling();
    this.pollingCancelled = false;
    let ticks = 0;
    const poll = () => {
      if (this.pollingCancelled) return;
      this.api
        .getImport(importId)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (result) => {
            if (this.pollingCancelled) return;
            this.commitResult.set(result);
            if (this.isTerminalStatus(result.status)) {
              this.committing.set(false);
              this.stopPolling();
              return;
            }
            ticks += 1;
            const delay = ticks < 10 ? 1000 : 2000;
            this.pollTimer = setTimeout(poll, delay);
          },
          // On a transient poll error, back off and try again — the
          // worker is still running, we just lost one round-trip.
          // The `pollingCancelled` guard stops the retry if the
          // component was destroyed between HTTP dispatch and the
          // error callback (`takeUntilDestroyed` won't fire the
          // callback after destroy, but a scheduled setTimeout does).
          error: () => {
            if (this.pollingCancelled) return;
            this.pollTimer = setTimeout(poll, 3000);
          },
        });
    };
    // Small initial delay so the first poll lands after the dispatch
    // ack has propagated through the DB.
    this.pollTimer = setTimeout(poll, 500);
    this.destroyRef.onDestroy(() => this.stopPolling());
  }

  private stopPolling(): void {
    this.pollingCancelled = true;
    if (this.pollTimer !== null) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
  }

  /** Cancel an in-flight processing import. Available on Step 4 when
   *  the status is ``processing``. On success, the poll loop picks up
   *  the ``cancelled`` status on its next tick. */
  protected cancelProcessing(): void {
    const meta = this.importMeta();
    if (!meta || this.cancelling()) return;
    this.cancelling.set(true);
    this.cancelError.set(null);
    this.api
      .cancelImport(meta.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.cancelling.set(false);
          this.commitResult.set(result);
          this.committing.set(false);
          this.stopPolling();
        },
        error: (err: HttpErrorResponse) => {
          this.cancelling.set(false);
          this.cancelError.set(extractApiError(err) ?? 'Could not cancel import.');
        },
      });
  }

  private triggerBlobDownload(blob: Blob, filename: string): void {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // --- Step 4 handlers ------------------------------------------------

  protected goToContacts(): void {
    void this.router.navigate(['/user/contacts']);
  }

  protected goToGroup(): void {
    const groupId = this.commitResult()?.created_group_id;
    if (!groupId) return;
    void this.router.navigate(['/user/contacts/groups', groupId, 'edit']);
  }

  // --- helpers --------------------------------------------------------

  private buildRunBody() {
    return {
      mapping: this.mapping(),
      create_group: this.createGroup(),
      group_name: this.createGroup() ? this.groupName().trim() : null,
      // DPDP: opt-in provenance picked on the map step. Persists on
      // every contact this import inserts (backend Step 0164).
      opt_in_source: this.optInSource(),
    };
  }

  private formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
}
