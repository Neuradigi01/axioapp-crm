import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { TemplateChannel, TemplatesApiService, VariableDef } from '../templates-api.service';

/**
 * Variable picker — shows the allowed `{{contact.*}} / {{org.*}} / etc.`
 * tags for the current channel, fetched from the Step-3 discovery
 * endpoint. Clicking a row emits the dot-path; the parent editor
 * inserts it at the focused textarea's cursor.
 *
 * Groups by namespace (contact / org / sender / lead / appointment /
 * quote / invoice / user) for readability — a 30+ entry flat list is
 * unscannable.
 */
@Component({
  selector: 'app-variable-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './variable-picker.component.html',
})
export class VariablePickerComponent {
  private readonly api = inject(TemplatesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly channel = input.required<TemplateChannel>();
  readonly insert = output<string>();

  protected readonly variables = signal<VariableDef[]>([]);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly grouped = computed<Array<{ namespace: string; rows: VariableDef[] }>>(() => {
    const groups = new Map<string, VariableDef[]>();
    for (const v of this.variables()) {
      const ns = v.key.split('.')[0] ?? 'other';
      const bucket = groups.get(ns);
      if (bucket) bucket.push(v);
      else groups.set(ns, [v]);
    }
    return Array.from(groups.entries())
      .map(([namespace, rows]) => ({ namespace, rows }))
      .sort((a, b) => a.namespace.localeCompare(b.namespace));
  });

  constructor() {
    // Re-fetch whenever the channel changes.
    effect(() => {
      const channel = this.channel();
      this.loading.set(true);
      this.loadError.set(null);
      this.api
        .variables(channel)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (rows) => {
            this.variables.set(rows);
            this.loading.set(false);
          },
          error: (err: HttpErrorResponse) => {
            this.variables.set([]);
            this.loading.set(false);
            this.loadError.set('Could not load variables.');
            void err;
          },
        });
    });
  }

  protected onInsert(def: VariableDef): void {
    this.insert.emit(`{{ ${def.key} }}`);
  }
}
