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
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  CatalogApiService,
  CatalogBulkImportResult,
  CatalogBulkImportRow,
  CatalogBulkImportRowError,
} from '../catalog-api.service';

/**
 * `/user/catalog/import` — CSV bulk-import wizard for catalog items.
 *
 *   Step 1 (upload):   drop / pick a .csv → client-side parse into
 *                      rows. Also accepts pasted CSV text so people
 *                      copying from Excel don't have to save a file.
 *   Step 2 (preview):  hits POST /catalog/bulk-import with dry_run=true.
 *                      Shows would-insert / would-skip counts + error
 *                      table (with row_index + reason).
 *   Step 3 (commit):   POST /catalog/bulk-import with dry_run=false,
 *                      renders the success card with a link back to
 *                      the catalog.
 *
 * Kept intentionally simple compared to the contacts import wizard —
 * catalog columns are fixed (no per-column mapping step): the CSV
 * header MUST match one of the expected keys or the row is skipped.
 */

const EXPECTED_COLUMNS = [
  'sku',
  'name',
  'description',
  'category',
  'price',
  'cost_price',
  'currency',
  'is_active',
  'tags',
] as const;

type ExpectedColumn = (typeof EXPECTED_COLUMNS)[number];

const ERROR_VISIBLE_LIMIT = 50;

interface ParseIssue {
  row_index: number;
  reason: string;
}

interface ParseOutcome {
  rows: CatalogBulkImportRow[];
  issues: ParseIssue[];
  missingRequired: string[];
  headerRow: string[];
}

@Component({
  selector: 'app-catalog-bulk-import-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
  templateUrl: './bulk-import.page.html',
})
export class CatalogBulkImportPageComponent {
  private readonly api = inject(CatalogApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly expectedColumns = EXPECTED_COLUMNS;
  protected readonly errorVisibleLimit = ERROR_VISIBLE_LIMIT;

  /** 1=upload · 2=preview · 3=success. */
  protected readonly step = signal<1 | 2 | 3>(1);

  // --- Step 1 ---------------------------------------------------------
  protected readonly selectedFileName = signal<string | null>(null);
  protected readonly pastedText = signal<string>('');
  protected readonly dragOver = signal(false);
  protected readonly parseError = signal<string | null>(null);
  protected readonly parseIssues = signal<ParseIssue[]>([]);
  protected readonly missingColumns = signal<string[]>([]);
  protected readonly parsedRows = signal<CatalogBulkImportRow[]>([]);

  // --- Step 2 ---------------------------------------------------------
  protected readonly dryRunLoading = signal(false);
  protected readonly dryRunError = signal<string | null>(null);
  protected readonly dryRunResult = signal<CatalogBulkImportResult | null>(null);
  protected readonly showAllErrors = signal(false);

  // --- Step 3 ---------------------------------------------------------
  protected readonly commitLoading = signal(false);
  protected readonly commitError = signal<string | null>(null);
  protected readonly commitResult = signal<CatalogBulkImportResult | null>(null);

  /** True when either dry-run or commit reported per-row errors — used
   *  by the template to reveal the "Download errors CSV" button. */
  protected readonly hasDownloadableErrors = computed(() => {
    const dr = this.dryRunResult();
    const cm = this.commitResult();
    return (dr?.errors.length ?? 0) + (cm?.errors.length ?? 0) > 0;
  });

  protected readonly canGoToPreview = computed(
    () => this.parsedRows().length > 0 && this.missingColumns().length === 0,
  );

  // --- Step 1: file & paste handlers ---------------------------------

  protected onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    input.value = '';
    if (!file) return;
    this.readFile(file);
  }

  protected onFileDropped(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(false);
    const file = event.dataTransfer?.files?.[0] ?? null;
    if (!file) return;
    this.readFile(file);
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(true);
  }

  protected onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(false);
  }

  private readFile(file: File): void {
    if (!/\.csv$/i.test(file.name)) {
      this.parseError.set('Pick a .csv file.');
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      this.parseError.set('CSV exceeds the 5 MB cap.');
      return;
    }
    this.selectedFileName.set(file.name);
    const reader = new FileReader();
    reader.onload = () => this.parseCsv(String(reader.result ?? ''));
    reader.onerror = () => this.parseError.set('Could not read that file.');
    reader.readAsText(file);
  }

  protected onPasteChange(event: Event): void {
    this.pastedText.set((event.target as HTMLTextAreaElement).value);
  }

  protected parsePasted(): void {
    const text = this.pastedText().trim();
    if (!text) {
      this.parseError.set('Paste some CSV text first.');
      return;
    }
    this.selectedFileName.set('(pasted)');
    this.parseCsv(text);
  }

  private parseCsv(text: string): void {
    this.parseError.set(null);
    this.parseIssues.set([]);
    this.missingColumns.set([]);
    this.parsedRows.set([]);

    const outcome = parseCsvContent(text);
    if (outcome.headerRow.length === 0) {
      this.parseError.set('CSV appears to be empty.');
      return;
    }
    if (outcome.missingRequired.length > 0) {
      this.missingColumns.set(outcome.missingRequired);
    }
    this.parseIssues.set(outcome.issues);
    this.parsedRows.set(outcome.rows);
  }

  // --- Step 2: dry-run --------------------------------------------------

  protected goToPreview(): void {
    if (!this.canGoToPreview()) return;
    this.step.set(2);
    this.runDryRun();
  }

  private runDryRun(): void {
    this.dryRunLoading.set(true);
    this.dryRunError.set(null);
    this.dryRunResult.set(null);
    this.api
      .bulkImport({ rows: this.parsedRows(), dry_run: true })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.dryRunResult.set(res);
          this.dryRunLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.dryRunError.set(extractApiError(err) ?? 'Could not preview the import.');
          this.dryRunLoading.set(false);
        },
      });
  }

  protected backToUpload(): void {
    this.step.set(1);
    this.dryRunResult.set(null);
    this.dryRunError.set(null);
    this.showAllErrors.set(false);
  }

  protected toggleShowAllErrors(): void {
    this.showAllErrors.update((v) => !v);
  }

  // --- Step 3: commit --------------------------------------------------

  protected commitImport(): void {
    this.commitLoading.set(true);
    this.commitError.set(null);
    this.commitResult.set(null);
    this.api
      .bulkImport({ rows: this.parsedRows(), dry_run: false })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.commitResult.set(res);
          this.commitLoading.set(false);
          this.step.set(3);
        },
        error: (err: HttpErrorResponse) => {
          this.commitError.set(extractApiError(err) ?? 'Could not commit the import.');
          this.commitLoading.set(false);
        },
      });
  }

  protected startOver(): void {
    this.step.set(1);
    this.selectedFileName.set(null);
    this.pastedText.set('');
    this.parsedRows.set([]);
    this.parseIssues.set([]);
    this.missingColumns.set([]);
    this.parseError.set(null);
    this.dryRunResult.set(null);
    this.dryRunError.set(null);
    this.commitResult.set(null);
    this.commitError.set(null);
    this.showAllErrors.set(false);
  }

  /** Compose an `errors.csv` client-side from whichever result carries
   *  errors (commit takes precedence over dry-run). Matches the shape
   *  the contacts / leads imports produce server-side: original catalog
   *  columns + `__row_number` + `__column` + `__value` + `__error_reason`.
   *  Catalog imports are synchronous, so the client already has all the
   *  data needed to render this report — no server round-trip. */
  protected downloadErrorsCsv(): void {
    const result = this.commitResult() ?? this.dryRunResult();
    if (!result || result.errors.length === 0) return;
    const rows = this.parsedRows();
    const csv = buildErrorsCsv(rows, result.errors);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'catalog-import-errors.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }
}

// --- CSV parsing --------------------------------------------------------

/** Minimal RFC-4180-ish CSV parser. Handles quoted fields (with escaped
 *  double-quotes) and both CRLF/LF line endings. Enough for the sheets
 *  operators actually copy out of Excel — for real 100k-row imports the
 *  server-side path is the source of truth. */
function parseCsvContent(text: string): ParseOutcome {
  const rows = tokenizeCsv(text);
  if (rows.length === 0) {
    return { rows: [], issues: [], missingRequired: [], headerRow: [] };
  }

  const header = rows[0].map((c) => c.trim().toLowerCase());
  const required: ExpectedColumn[] = ['sku', 'name', 'price'];
  const missing = required.filter((r) => !header.includes(r));
  if (missing.length > 0) {
    return { rows: [], issues: [], missingRequired: missing, headerRow: header };
  }

  const skuIdx = header.indexOf('sku');
  const nameIdx = header.indexOf('name');
  const descIdx = header.indexOf('description');
  const catIdx = header.indexOf('category');
  const priceIdx = header.indexOf('price');
  const costIdx = header.indexOf('cost_price');
  const currIdx = header.indexOf('currency');
  const activeIdx = header.indexOf('is_active');
  const tagsIdx = header.indexOf('tags');

  const out: CatalogBulkImportRow[] = [];
  const issues: ParseIssue[] = [];

  for (let i = 1; i < rows.length; i += 1) {
    const row = rows[i];
    if (row.every((c) => c.trim() === '')) continue;

    const sku = (row[skuIdx] ?? '').trim();
    const name = (row[nameIdx] ?? '').trim();
    const priceRaw = (row[priceIdx] ?? '').trim();
    if (!sku || !name || !priceRaw) {
      issues.push({ row_index: i, reason: 'Missing sku, name, or price' });
      continue;
    }
    const price = Number(priceRaw);
    if (!Number.isFinite(price)) {
      issues.push({ row_index: i, reason: `Invalid price "${priceRaw}"` });
      continue;
    }

    const parsed: CatalogBulkImportRow = { sku, name, price };
    if (descIdx >= 0) {
      const v = (row[descIdx] ?? '').trim();
      if (v) parsed.description = v;
    }
    if (catIdx >= 0) {
      const v = (row[catIdx] ?? '').trim();
      if (v) parsed.category = v;
    }
    if (costIdx >= 0) {
      const raw = (row[costIdx] ?? '').trim();
      if (raw) {
        const n = Number(raw);
        if (!Number.isFinite(n)) {
          issues.push({ row_index: i, reason: `Invalid cost_price "${raw}"` });
          continue;
        }
        parsed.cost_price = n;
      }
    }
    if (currIdx >= 0) {
      const v = (row[currIdx] ?? '').trim();
      if (v) parsed.currency = v;
    }
    if (activeIdx >= 0) {
      const v = (row[activeIdx] ?? '').trim().toLowerCase();
      if (v) parsed.is_active = !['false', '0', 'no', 'n'].includes(v);
    }
    if (tagsIdx >= 0) {
      const v = (row[tagsIdx] ?? '').trim();
      if (v) {
        parsed.tags = v
          .split(/[,;|]/)
          .map((t) => t.trim())
          .filter((t) => t.length > 0);
      }
    }
    out.push(parsed);
  }

  return { rows: out, issues, missingRequired: [], headerRow: header };
}

/** RFC-4180-ish tokenizer — one 2D array (rows × cells). */
function tokenizeCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let i = 0;
  let inQuotes = false;
  const len = text.length;

  while (i < len) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i += 1;
        continue;
      }
      cell += ch;
      i += 1;
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
      i += 1;
      continue;
    }
    if (ch === ',') {
      row.push(cell);
      cell = '';
      i += 1;
      continue;
    }
    if (ch === '\r') {
      i += 1;
      continue;
    }
    if (ch === '\n') {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
      i += 1;
      continue;
    }
    cell += ch;
    i += 1;
  }
  if (cell.length > 0 || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

// --- Errors CSV builder -------------------------------------------------

/** Compose an `errors.csv` payload from the parsed rows + backend errors.
 *  Output matches the shape the contacts / leads imports produce
 *  server-side:
 *
 *      <original catalog columns…>, __row_number, __column, __value, __error_reason
 *
 *  Client-side generation is safe here because catalog imports are
 *  synchronous — the browser still holds the parsed rows that were sent
 *  to the backend, so no server round-trip is needed to render the
 *  operator's fix-and-re-upload report. */
function buildErrorsCsv(
  rows: readonly CatalogBulkImportRow[],
  errors: readonly CatalogBulkImportRowError[],
): string {
  const columns = [
    'sku',
    'name',
    'description',
    'category',
    'price',
    'cost_price',
    'currency',
    'is_active',
    'tags',
    '__row_number',
    '__column',
    '__value',
    '__error_reason',
  ];
  const lines: string[] = [columns.join(',')];
  for (const err of errors) {
    const row = rows[err.row_index];
    const record: Record<string, unknown> = row
      ? {
          sku: row.sku,
          name: row.name,
          description: row.description ?? '',
          category: row.category ?? '',
          price: row.price ?? '',
          cost_price: row.cost_price ?? '',
          currency: row.currency ?? '',
          is_active: row.is_active === undefined ? '' : String(row.is_active),
          tags: (row.tags ?? []).join('|'),
        }
      : { sku: err.sku };
    record['__row_number'] = err.row_index + 1;
    record['__column'] = err.column ?? '';
    record['__value'] = err.value ?? '';
    record['__error_reason'] = err.reason;
    lines.push(columns.map((c) => csvEscape(record[c])).join(','));
  }
  return lines.join('\r\n') + '\r\n';
}

function csvEscape(value: unknown): string {
  if (value === null || value === undefined) return '';
  const str = String(value);
  if (str.includes(',') || str.includes('"') || str.includes('\n') || str.includes('\r')) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}
