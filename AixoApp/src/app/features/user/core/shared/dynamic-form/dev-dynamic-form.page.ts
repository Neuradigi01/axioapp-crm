import { ChangeDetectionStrategy, Component, signal } from '@angular/core';

import { DynamicFormComponent } from './dynamic-form.component';
import { FieldDef, FormValue } from './types';

/**
 * Storybook-style smoke test page for `<app-dynamic-form>`. Renders one
 * field of every supported `field_type` against an in-memory definition
 * list and echoes the live value + validity back to the screen. Wired
 * into `userRoutes` behind `!environment.production` so it is reachable
 * only in dev builds.
 */
const DEMO_FIELDS: ReadonlyArray<FieldDef> = [
  {
    field_key: 'full_name',
    field_label: 'Full name',
    field_type: 'text',
    is_required: true,
    validation: { minLength: 2, maxLength: 80 },
  },
  {
    field_key: 'age',
    field_label: 'Age',
    field_type: 'number',
    is_required: true,
    validation: { min: 0, max: 120 },
  },
  {
    field_key: 'budget_inr',
    field_label: 'Budget',
    field_type: 'currency',
    validation: { min: 0 },
  },
  {
    field_key: 'email',
    field_label: 'Email',
    field_type: 'email',
  },
  {
    field_key: 'phone',
    field_label: 'Phone',
    field_type: 'phone',
  },
  {
    field_key: 'visit_date',
    field_label: 'Showroom visit date',
    field_type: 'date',
  },
  {
    field_key: 'follow_up_at',
    field_label: 'Follow-up time',
    field_type: 'datetime',
  },
  {
    field_key: 'marketing_opt_in',
    field_label: 'Receive marketing emails',
    field_type: 'boolean',
  },
  {
    field_key: 'preferred_wood',
    field_label: 'Preferred wood',
    field_type: 'select',
    options: { choices: ['Teak', 'Oak', 'Mahogany', 'Sheesham'] },
    is_required: true,
  },
  {
    field_key: 'rooms_to_furnish',
    field_label: 'Rooms to furnish',
    field_type: 'multiselect',
    options: { choices: ['Living', 'Bedroom', 'Dining', 'Study', 'Outdoor'] },
  },
];

@Component({
  selector: 'app-dev-dynamic-form-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DynamicFormComponent],
  templateUrl: './dev-dynamic-form.page.html',
})
export class DevDynamicFormPageComponent {
  protected readonly fields = signal<FieldDef[]>([...DEMO_FIELDS]);
  protected readonly value = signal<FormValue>({});
  protected readonly liveValue = signal<FormValue>({});
  protected readonly valid = signal<boolean>(false);
  protected readonly loading = signal<boolean>(false);

  protected get valuePreview(): string {
    return JSON.stringify(this.liveValue(), null, 2);
  }

  protected onValueChange(v: FormValue): void {
    this.liveValue.set(v);
  }

  protected onValidityChange(v: boolean): void {
    this.valid.set(v);
  }

  protected toggleLoading(): void {
    this.loading.update((v) => !v);
  }
}
