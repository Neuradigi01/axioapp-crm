import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../../shared/forms/mobile-select.component';
import { CanvasNode } from '../canvas-state.service';
import { ConditionsBuilderComponent } from '../conditions-builder.component';
import { ConditionNode, EVENT_TYPES, variableGroupsForEvent } from './editor-contract';

type ReEnrollmentRule = 'once' | 'daily' | 'never';

const RE_ENROLLMENT_OPTIONS: Array<{
  value: ReEnrollmentRule;
  label: string;
  description: string;
}> = [
  {
    value: 'once',
    label: 'Once per contact',
    description: 'A contact who already finished this workflow won’t re-enrol.',
  },
  {
    value: 'daily',
    label: 'Up to once per day',
    description: 'A contact can re-enrol after 24h.',
  },
  {
    value: 'never',
    label: 'Always allow',
    description: 'No re-enrolment guard — every event fires.',
  },
];

/**
 * Trigger node editor. Operator picks:
 *   - `event_type` from the catalogue (Step-5 backend's `EVENT_DESCRIPTIONS`).
 *   - `re_enrollment_rule` (mirrors the workflow-level rule for this
 *     specific trigger — workflows-spec Step 1 left room for per-
 *     trigger override; Step 15 surfaces it).
 *   - `conditions` AST (via the shared builder; required to keep the
 *     trigger from firing on every event of that type).
 *
 * Valid when `event_type` is set. Conditions are optional but
 * recommended (without them, every event of the chosen type fires).
 */

@Component({
  selector: 'app-trigger-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, ConditionsBuilderComponent, MobileSelectComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './trigger-editor.component.html',
})
export class TriggerEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly eventTypes = EVENT_TYPES;
  readonly reEnrollmentOptions = RE_ENROLLMENT_OPTIONS;

  /** `<crm-mobile-select>` needs a `{value, label}` list. Map each
   *  registry entry once here so the template can bind directly. */
  readonly eventTypeOptions = computed<ReadonlyArray<MobileSelectOption>>(() =>
    EVENT_TYPES.map((e) => ({ value: e.type, label: `${e.label} (${e.type})` })),
  );

  readonly reEnrollmentSelectOptions: ReadonlyArray<MobileSelectOption> = RE_ENROLLMENT_OPTIONS.map(
    (opt) => ({ value: opt.value, label: opt.label }),
  );

  readonly eventType = computed<string>(() => (this.node().config?.['event_type'] as string) ?? '');

  readonly reEnrollmentRule = computed<ReEnrollmentRule>(
    () => (this.node().config?.['re_enrollment_rule'] as ReEnrollmentRule) ?? 'once',
  );

  readonly conditions = computed<ConditionNode | null>(
    () => (this.node().config?.['conditions'] as ConditionNode | null) ?? null,
  );

  readonly variableGroups = computed(() => variableGroupsForEvent(this.eventType()));

  constructor() {
    effect(() => {
      const valid = this.eventType().length > 0;
      this.validityChange.emit(valid);
    });
  }

  onEventTypeChange(value: string): void {
    this.configChange.emit({ event_type: value });
  }

  onReEnrollmentChange(value: ReEnrollmentRule): void {
    this.configChange.emit({ re_enrollment_rule: value });
  }

  onConditionsChange(tree: ConditionNode | null): void {
    this.configChange.emit({ conditions: tree });
  }
}
