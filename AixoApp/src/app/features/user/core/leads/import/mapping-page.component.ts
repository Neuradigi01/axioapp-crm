import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';
import {
  ImportPreset,
  ImportsApiService,
  LeadImport,
  MappingTarget,
  PreviewResponse,
  SourcePlatform,
} from './imports-api.service';

/**
 * `/user/leads/import/:id/mapping` — the column-mapping UI.
 *
 * Flow:
 *
 *   1. Load the import row, the targets list, the platform's presets,
 *      and a preview of the first 5 data rows — all in parallel.
 *   2. Pre-fill the `{csv_column → crm_target}` mapping with this
 *      priority: most-recent org-owned preset > system preset >
 *      heuristic match (exact-then-substring on label or key).
 *   3. Per CSV column row: dropdown of grouped targets (Standard
 *      contact / Standard lead / Custom fields). Status marker
 *      (yellow=unmapped / green=mapped / red=invalid). Required
 *      targets show a banner above Commit until they're satisfied.
 *   4. Preview pane below: 5 rows projected through the current
 *      mapping — reactively re-renders when the user changes any
 *      dropdown.
 *   5. Action bar: Save-as-preset / Cancel / Commit. Commit POSTs
 *      the mapping and navigates to /user/leads/import/:id/result.
 *
 * Imports already past `awaiting_mapping` redirect to the result
 * page so refresh on a completed import doesn't show an empty form.
 */

const REQUIRED_TARGETS = ['contact.full_name'] as const;

@Component({
  selector: 'app-import-mapping-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
  templateUrl: './mapping-page.component.html',
})
export class MappingPageComponent {
  private readonly api = inject(ImportsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly importId = this.route.snapshot.paramMap.get('id') ?? '';

  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);

  protected readonly importRow = signal<LeadImport | null>(null);
  protected readonly targets = signal<MappingTarget[]>([]);
  protected readonly presets = signal<ImportPreset[]>([]);
  protected readonly preview = signal<PreviewResponse | null>(null);

  /** Current mapping — keyed by csv column name. */
  protected readonly mapping = signal<Record<string, string | null>>({});

  /** Save-as-preset modal. */
  protected readonly savePresetOpen = signal(false);
  protected readonly presetName = signal('');
  protected readonly saving = signal(false);
  protected readonly savePresetError = signal<string | null>(null);

  /** Commit / Cancel state. */
  protected readonly committing = signal(false);
  protected readonly cancelling = signal(false);
  protected readonly actionError = signal<string | null>(null);

  // --- Derived state ---------------------------------------------------

  /** Targets grouped for the dropdown UI. */
  protected readonly targetGroups = computed(() => {
    const ts = this.targets();
    return {
      contact: ts.filter((t) => t.key.startsWith('contact.')),
      lead: ts.filter((t) => t.key.startsWith('lead.')),
      custom: ts.filter((t) => t.custom),
    };
  });

  /** Set of target keys mapped to at least one column. */
  protected readonly mappedTargetSet = computed(() => {
    return new Set(Object.values(this.mapping()).filter((v): v is string => !!v));
  });

  /** Required targets that are not yet mapped to any column. */
  protected readonly missingRequired = computed(() => {
    const mapped = this.mappedTargetSet();
    const required = this.targets().filter((t) => t.required);
    return required.filter((t) => !mapped.has(t.key));
  });

  /** Duplicate target mappings (same CRM field picked by 2+ columns),
   * with the offending CSV columns so the banner can name them. */
  protected readonly duplicateDetails = computed(() => {
    const byTarget = new Map<string, string[]>();
    for (const [col, v] of Object.entries(this.mapping())) {
      if (!v) continue;
      byTarget.set(v, [...(byTarget.get(v) ?? []), col]);
    }
    const labels = new Map(this.targets().map((t) => [t.key, t.label]));
    return [...byTarget.entries()]
      .filter(([, cols]) => cols.length > 1)
      .map(([key, cols]) => ({ key, label: labels.get(key) ?? key, columns: cols }));
  });

  /** Just the duplicated target keys — per-row status marker + commit gate. */
  protected readonly duplicateTargets = computed(
    () => new Set(this.duplicateDetails().map((d) => d.key)),
  );

  /** Commit is allowed iff every required target is mapped and no duplicates. */
  protected readonly canCommit = computed(
    () =>
      !this.committing() &&
      !this.cancelling() &&
      this.missingRequired().length === 0 &&
      this.duplicateTargets().size === 0,
  );

  /** Preview rows projected through the current mapping. Each item is
   * `{crmFieldKey: value}` for the visible mapped fields. */
  protected readonly previewMapped = computed(() => {
    const p = this.preview();
    const m = this.mapping();
    if (!p) return [];
    const colIndex: Record<string, number> = {};
    p.columns.forEach((c, i) => (colIndex[c] = i));
    return p.rows.map((row) => {
      const out: Record<string, string | null> = {};
      for (const [csvCol, crmField] of Object.entries(m)) {
        if (!crmField) continue;
        const idx = colIndex[csvCol];
        out[crmField] = idx !== undefined ? (row[idx] ?? null) : null;
      }
      return out;
    });
  });

  // --- Lifecycle ------------------------------------------------------

  constructor() {
    if (!this.importId) {
      this.loading.set(false);
      this.loadError.set('No import id in the route.');
      return;
    }
    this.loadAll();
  }

  // --- Loading --------------------------------------------------------

  private loadAll(): void {
    this.api
      .get(this.importId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          // Redirect terminal/post-mapping imports to the result page —
          // mapping after the job has committed makes no sense.
          if (row.status !== 'awaiting_mapping') {
            this.router.navigate(['/user/leads/import', this.importId, 'result'], {
              replaceUrl: true,
            });
            return;
          }
          this.importRow.set(row);
          this.loadDependentData(row);
        },
        error: () => {
          this.loading.set(false);
          this.loadError.set('Could not load this import.');
        },
      });
  }

  private loadDependentData(row: LeadImport): void {
    const platform = row.source_platform as SourcePlatform;
    forkJoin({
      targets: this.api.listTargets().pipe(catchError(() => of([]))),
      presets: this.api.listPresets(platform).pipe(catchError(() => of([]))),
      preview: this.api
        .preview(this.importId, 5)
        .pipe(catchError(() => of({ columns: [], rows: [] }))),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(({ targets, presets, preview }) => {
        this.targets.set(targets);
        this.presets.set(presets);
        this.preview.set(preview);
        this.mapping.set(this.buildInitialMapping(preview.columns, targets, presets));
        this.loading.set(false);
      });
  }

  /** Pre-fill priority: org-owned preset > system preset > heuristic.
   * Each target is assigned to at most ONE column (first in file order
   * wins) — pre-fill must never produce a duplicate-mapping state, or
   * the user's own selection gets flagged as the conflict. */
  private buildInitialMapping(
    columns: string[],
    targets: MappingTarget[],
    presets: ImportPreset[],
  ): Record<string, string | null> {
    const out: Record<string, string | null> = {};
    const targetKeys = new Set(targets.map((t) => t.key));
    const used = new Set<string>();

    // Pick the most recent org-owned preset; fall back to system.
    const orgPreset = presets.find((p) => !p.is_system);
    const systemPreset = presets.find((p) => p.is_system);
    const active = orgPreset ?? systemPreset;
    const presetMap = active?.mapping ?? {};

    for (const col of columns) {
      // Preset wins if its target is still valid and not already taken
      // by an earlier column (presets may list header variants — e.g.
      // "Phone" and "Mobile" both → contact.phone — for CSVs that only
      // contain one of them).
      const fromPreset = presetMap[col];
      const target =
        fromPreset && targetKeys.has(fromPreset) && !used.has(fromPreset)
          ? fromPreset
          : this.heuristicMatch(col, targets, used);
      if (target) used.add(target);
      out[col] = target;
    }
    return out;
  }

  private heuristicMatch(
    csvColumn: string,
    targets: MappingTarget[],
    used: ReadonlySet<string>,
  ): string | null {
    const c = csvColumn.toLowerCase().trim();
    if (!c) return null;
    // 1. Exact match on label or key (case-insensitive).
    for (const t of targets) {
      if (used.has(t.key)) continue;
      if (c === t.label.toLowerCase() || c === t.key.toLowerCase()) {
        return t.key;
      }
    }
    // 2. Substring match — pick the first plausible target. Order
    // matters: targets are listed standard-contact then standard-lead
    // then custom, so contact-side matches win when ambiguous (a
    // column called "name" maps to contact.full_name, not lead.budget).
    for (const t of targets) {
      if (used.has(t.key)) continue;
      const tl = t.label.toLowerCase();
      const tk = t.key.toLowerCase();
      if (c.includes(tl) || tl.includes(c) || c.includes(tk)) {
        return t.key;
      }
    }
    return null;
  }

  // --- User actions ---------------------------------------------------

  protected onMappingChange(csvColumn: string, event: Event): void {
    const select = event.target as HTMLSelectElement;
    const value = select.value || null;
    this.mapping.update((m) => ({ ...m, [csvColumn]: value }));
  }

  protected sampleValue(csvColumn: string): string | null {
    const p = this.preview();
    if (!p) return null;
    const idx = p.columns.indexOf(csvColumn);
    if (idx < 0) return null;
    const first = p.rows[0];
    return first?.[idx] ?? null;
  }

  protected statusFor(csvColumn: string): 'unmapped' | 'mapped' | 'duplicate' {
    const v = this.mapping()[csvColumn];
    if (!v) return 'unmapped';
    if (this.duplicateTargets().has(v)) return 'duplicate';
    return 'mapped';
  }

  // --- Save preset ---------------------------------------------------

  protected openSavePreset(): void {
    this.presetName.set('');
    this.savePresetError.set(null);
    this.savePresetOpen.set(true);
  }

  protected closeSavePreset(): void {
    this.savePresetOpen.set(false);
  }

  protected onPresetNameInput(event: Event): void {
    this.presetName.set((event.target as HTMLInputElement).value);
  }

  protected saveAsPreset(): void {
    const row = this.importRow();
    if (!row) return;
    this.saving.set(true);
    this.savePresetError.set(null);
    this.api
      .createPreset({
        name: this.presetName().trim() || null,
        source_platform: row.source_platform as SourcePlatform,
        mapping: this.mapping(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.savePresetOpen.set(false);
          // Refresh the presets list so the new one shows up next time.
          this.api
            .listPresets(row.source_platform as SourcePlatform)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((presets) => this.presets.set(presets));
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.savePresetError.set(extractApiError(err) ?? 'Could not save preset.');
        },
      });
  }

  // --- Cancel + Commit -----------------------------------------------

  protected cancelImport(): void {
    if (!confirm('Cancel this import? The uploaded file will be discarded.')) return;
    this.cancelling.set(true);
    this.actionError.set(null);
    this.api
      .cancel(this.importId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.cancelling.set(false);
          this.router.navigate(['/user/leads']);
        },
        error: (err: HttpErrorResponse) => {
          this.cancelling.set(false);
          this.actionError.set(extractApiError(err) ?? 'Could not cancel import.');
        },
      });
  }

  protected commit(): void {
    if (!this.canCommit()) return;
    this.committing.set(true);
    this.actionError.set(null);
    this.api
      .commit(this.importId, this.mapping())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.committing.set(false);
          this.router.navigate(['/user/leads/import', this.importId, 'result']);
        },
        error: (err: HttpErrorResponse) => {
          this.committing.set(false);
          this.actionError.set(extractApiError(err) ?? 'Could not commit mapping.');
        },
      });
  }

  /** Static accessor for the template — required targets list. */
  protected readonly requiredTargets = REQUIRED_TARGETS;
}
