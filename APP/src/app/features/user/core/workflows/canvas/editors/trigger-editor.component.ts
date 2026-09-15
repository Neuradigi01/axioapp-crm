import { CommonModule } from '@angular/common';
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
import { FormsModule } from '@angular/forms';

import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../../shared/forms/mobile-select.component';
import { CustomEventTypeOption, WorkflowsApiService } from '../../workflows-api.service';
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
  private readonly api = inject(WorkflowsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly eventTypes = EVENT_TYPES;
  readonly reEnrollmentOptions = RE_ENROLLMENT_OPTIONS;

  /** Org-defined events fetched from `GET /workflows/custom-event-types`.
   *  Populated once on component init; a network error leaves the list
   *  empty so built-in events remain pickable. */
  private readonly customEvents = signal<readonly CustomEventTypeOption[]>([]);

  /** `<crm-mobile-select>` needs a `{value, label}` list. Merge the
   *  static built-in catalog with the org's custom events (fetched at
   *  init). Custom events publish on the bus as `custom.<key>` and
   *  route into the workflow matcher via the wildcard subscription.
   *
   *  Safety net: if the stored `event_type` isn't in either list
   *  (e.g. a seeded workflow uses a specialised event, or a custom
   *  event was deleted after the workflow was saved), append a
   *  synthetic option so the picker still shows the current value
   *  instead of the "— pick an event —" placeholder. */
  readonly eventTypeOptions = computed<ReadonlyArray<MobileSelectOption>>(() => {
    const base: MobileSelectOption[] = EVENT_TYPES.map((e) => ({
      value: e.type,
      label: `${e.label} (${e.type})`,
    }));
    for (const c of this.customEvents()) {
      base.push({ value: c.event_type, label: `${c.label} (${c.event_type})` });
    }
    const current = this.eventType();
    if (
      current &&
      !EVENT_TYPES.some((e) => e.type === current) &&
      !this.customEvents().some((c) => c.event_type === current)
    ) {
      base.push({ value: current, label: current });
    }
    return base;
  });

  /** Description rendered under the picker. Falls back through the
   *  static catalog first, then the fetched custom events, so custom
   *  events get their org-supplied description under the picker. */
  readonly selectedEventDescription = computed<string>(() => {
    const current = this.eventType();
    if (!current) return '';
    const builtin = EVENT_TYPES.find((e) => e.type === current);
    if (builtin) return builtin.description;
    const custom = this.customEvents().find((c) => c.event_type === current);
    return custom?.description ?? '';
  });

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
    this.api
      .listCustomEventTypes()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (entries) => this.customEvents.set(entries),
        error: () => this.customEvents.set([]),
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
