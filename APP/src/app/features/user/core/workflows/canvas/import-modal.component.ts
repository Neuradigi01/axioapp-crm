import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { WorkflowExportBody } from '../workflows-api.service';


/**
 * Import-from-JSON modal — file picker + client-side validation.
 *
 * Validates the JSON's top-level shape (required keys + `graph.nodes`
 * + `graph.edges` arrays) before allowing submit. Bad files surface
 * an inline error rather than hitting the server.
 *
 * Submits the parsed body up to the parent via `(confirm)`, which
 * POSTs `/workflows/import` and routes to the new draft on success.
 */


const REQUIRED_TOP_KEYS = [
  'name',
  'category',
  'graph',
  're_enrollment_rule',
  'is_marketing',
  'schema_version',
];


@Component({
  selector: 'app-import-modal',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './import-modal.component.html',
})
export class ImportModalComponent {
  readonly cancel = output<void>();
  readonly confirm = output<{ body: WorkflowExportBody; name: string | null }>();

  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly fileName = signal<string | null>(null);
  readonly parsed = signal<WorkflowExportBody | null>(null);
  readonly overrideName = signal<string>('');

  readonly canSubmit = computed(
    () => this.parsed() !== null && !this.busy(),
  );

  onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    this.error.set(null);
    this.parsed.set(null);
    this.fileName.set(null);
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      this.error.set('File exceeds the 5 MB cap.');
      return;
    }
    this.fileName.set(file.name);
    file
      .text()
      .then((text) => {
        try {
          const data = JSON.parse(text) as unknown;
          this.validateShape(data);
          const body = data as WorkflowExportBody;
          this.parsed.set(body);
          this.overrideName.set(body.name);
        } catch (err) {
          this.error.set(
            err instanceof Error
              ? err.message
              : 'JSON parse failed — is this a workflow export?',
          );
        }
      })
      .catch(() => this.error.set('Could not read the file.'));
  }

  private validateShape(data: unknown): void {
    if (typeof data !== 'object' || data === null || Array.isArray(data)) {
      throw new Error('Top-level JSON must be an object.');
    }
    const obj = data as Record<string, unknown>;
    const missing = REQUIRED_TOP_KEYS.filter((k) => !(k in obj));
    if (missing.length > 0) {
      throw new Error(
        `Missing required key(s): ${missing.join(', ')}.`,
      );
    }
    const graph = obj['graph'];
    if (
      typeof graph !== 'object' ||
      graph === null ||
      !Array.isArray((graph as { nodes?: unknown }).nodes) ||
      !Array.isArray((graph as { edges?: unknown }).edges)
    ) {
      throw new Error('`graph` must be `{ nodes: [], edges: [] }`.');
    }
    const schemaVersion = obj['schema_version'];
    if (schemaVersion !== 1) {
      throw new Error(
        `Unsupported schema_version ${schemaVersion}. This app only imports schema_version=1.`,
      );
    }
  }

  onSubmit(): void {
    const body = this.parsed();
    if (!body) return;
    this.busy.set(true);
    const finalName = this.overrideName().trim() || body.name;
    this.confirm.emit({ body, name: finalName });
  }
}
