import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

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

const FIELD_TARGETS: FieldTargetOption[] = [
  { value: 'skip', label: 'Skip this column' },
  { value: 'full_name', label: 'Full name' },
  { value: 'phone', label: 'Phone' },
  { value: 'email', label: 'Email' },
  { value: 'source', label: 'Source' },
  { value: 'tag', label: 'Tag' },
];

const VALID_TARGET_SET = new Set<ContactFieldTarget>(
  FIELD_TARGETS.map((t) => t.value),
);

const ACCEPT_EXTENSIONS = ['.xlsx', '.csv'] as const;

/** Errors past this count get hidden behind an "expand" toggle so an
 * import with 5000 row errors doesn't melt the browser. */
const ERROR_VISIBLE_LIMIT = 50;

@Component({
  selector: 'app-contact-import-wizard-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule, BulkImportOptInStepComponent],
  templateUrl: './import-wizard.page.html',
})
export class ContactImportWizardPageComponent {
  /** Step 22 — DPDP opt-in provenance picked on the map step.
   *  Null until the operator picks one; gates the Continue button. */
  protected readonly optInSource = signal<WhatsAppOptInSource | null>(null);

  protected setOptInSource(source: WhatsAppOptInSource): void {
    this.optInSource.set(source);
  }

  private readonly api = inject(ContactsApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly fieldTargets = FIELD_TARGETS;
  protected readonly errorVisibleLimit = ERROR_VISIBLE_LIMIT;

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
    return (
      dr !== null &&
      dr.will_insert > 0 &&
      !this.committing() &&
      !this.groupNameRequired()
    );
  });

  protected readonly visibleErrors = computed(() => {
    const errs = this.dryRunResult()?.errors ?? [];
    return this.errorsExpanded() ? errs : errs.slice(0, ERROR_VISIBLE_LIMIT);
  });

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
            safe[col] = VALID_TARGET_SET.has(guess) ? guess : 'skip';
          }
          this.mapping.set(safe);
          this.step.set(2);
        },
        error: (err: HttpErrorResponse) => {
          this.uploading.set(false);
          this.uploadError.set(
            extractApiError(err) ??
              'Upload failed — please try again or check the file format.',
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
    const value = (event.target as HTMLSelectElement)
      .value as ContactFieldTarget;
    this.mapping.update((m) => ({ ...m, [column]: value }));
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
          this.dryRunError.set(
            extractApiError(err) ?? 'Could not preview the import.',
          );
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
    this.api
      .commitImport(meta.id, this.buildRunBody())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.committing.set(false);
          this.commitResult.set(result);
          this.step.set(4);
        },
        error: (err: HttpErrorResponse) => {
          this.committing.set(false);
          this.commitError.set(
            extractApiError(err) ?? 'Could not commit the import.',
          );
        },
      });
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
    };
  }

  private formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
}
