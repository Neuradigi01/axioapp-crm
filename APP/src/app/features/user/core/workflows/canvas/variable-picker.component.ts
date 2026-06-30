import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { VariableGroup, variableGroupsForEvent } from './editors/editor-contract';


/**
 * Context-aware variable picker.
 *
 * The parent passes `eventType` (the trigger's `event_type` config) and
 * we surface the relevant variable groups via
 * `variableGroupsForEvent`. When `eventType` is null / empty, only
 * `ALWAYS_AVAILABLE` is shown.
 *
 * Selecting a path emits `(insert)` with the `{{path}}` mustache form
 * — the parent textarea / input concatenates at the caret. The picker
 * also has a small search input for fast filtering.
 */


@Component({
  selector: 'app-variable-picker',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './variable-picker.component.html',
})
export class VariablePickerComponent {
  readonly eventType = input<string | null>(null);
  readonly insert = output<string>();

  readonly query = signal('');

  readonly groups = computed<VariableGroup[]>(() =>
    variableGroupsForEvent(this.eventType()),
  );

  readonly filtered = computed<VariableGroup[]>(() => {
    const q = this.query().trim().toLowerCase();
    if (!q) return this.groups();
    return this.groups()
      .map((g) => ({
        label: g.label,
        paths: g.paths.filter(
          (p) =>
            p.path.toLowerCase().includes(q) ||
            p.label.toLowerCase().includes(q) ||
            p.description.toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.paths.length > 0);
  });

  onPathClick(path: string): void {
    this.insert.emit(`{{${path}}}`);
  }
}
