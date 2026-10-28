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
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { ImportsApiService, SourcePlatform } from './imports-api.service';

/**
 * `/user/leads/import` — first user-facing surface of the bulk-import
 * track. Workflow:
 *
 *   1. User drags a CSV/XLSX (or clicks to browse) into the file zone.
 *   2. Picks the source platform (Zoho / HubSpot / Salesforce /
 *      Freshsales / Generic / Custom) — the choice is later used by
 *      the mapping page to pre-fill defaults from the system preset.
 *   3. Optionally names the import; auto-named from filename otherwise.
 *   4. Clicks Upload → `POST /leads/import/upload` (multipart).
 *   5. Backend creates the job row in `awaiting_mapping` → router
 *      pushes the user to `/user/leads/import/:id/mapping`
 *      (Step 5; placeholder until then).
 *
 * Backend caps (10 MB / 50,000 rows / CSV+XLSX only) are enforced
 * server-side; the page surfaces server errors verbatim. Client-side
 * we only check that a file + platform are both selected before
 * enabling the Upload button.
 */

interface PlatformOption {
  value: SourcePlatform;
  label: string;
}

const PLATFORMS: PlatformOption[] = [
  { value: 'zoho', label: 'Zoho CRM' },
  { value: 'hubspot', label: 'HubSpot' },
  { value: 'salesforce', label: 'Salesforce' },
  { value: 'freshsales', label: 'Freshsales' },
  { value: 'generic_csv', label: 'Generic CSV' },
  { value: 'custom', label: 'Custom / Other' },
];

@Component({
  selector: 'app-import-upload-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
  templateUrl: './upload-page.component.html',
})
export class UploadPageComponent {
  private readonly api = inject(ImportsApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly platforms = PLATFORMS;

  protected readonly selectedFile = signal<File | null>(null);
  protected readonly sourcePlatform = signal<SourcePlatform>('zoho');
  protected readonly name = signal<string>('');
  protected readonly dragOver = signal(false);
  protected readonly uploading = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly canSubmit = computed(
    () => this.selectedFile() !== null && this.sourcePlatform() !== null && !this.uploading(),
  );

  protected readonly fileSizeLabel = computed(() => {
    const f = this.selectedFile();
    if (!f) return null;
    return this.formatBytes(f.size);
  });

  protected onPlatformChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value as SourcePlatform;
    this.sourcePlatform.set(value);
  }

  protected onNameInput(event: Event): void {
    this.name.set((event.target as HTMLInputElement).value);
  }

  protected onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    this.setFile(file);
  }

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

  protected clearFile(): void {
    this.selectedFile.set(null);
    this.error.set(null);
  }

  protected submit(): void {
    const file = this.selectedFile();
    if (!file) return;
    this.uploading.set(true);
    this.error.set(null);
    this.api
      .upload(file, this.sourcePlatform(), this.name().trim() || null)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.uploading.set(false);
          this.router.navigate(['/user/leads/import', row.id, 'mapping']);
        },
        error: (err: HttpErrorResponse) => {
          this.uploading.set(false);
          this.error.set(
            extractApiError(err) ?? 'Upload failed — please try again or check the file format.',
          );
        },
      });
  }

  private setFile(file: File | null): void {
    if (file) {
      const name = file.name.toLowerCase();
      const okExtension = name.endsWith('.csv') || name.endsWith('.xlsx');
      if (!okExtension) {
        this.error.set('Only .csv and .xlsx files are accepted. Pick a different file.');
        this.selectedFile.set(null);
        return;
      }
    }
    this.selectedFile.set(file);
    this.error.set(null);
  }

  private formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
}
