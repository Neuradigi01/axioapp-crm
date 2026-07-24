import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import {
  AutomationsApiService,
  EnumOption,
  FieldSpec,
  FieldSpecType,
} from '../automations-api.service';
import { ConditionBuilderComponent } from './condition-builder.component';

/**
 * Unit coverage for the data-driven condition builder
 * (tasks/automation-conditions/ Step 3).
 *
 * Fixtures give the component a small `FieldSpec[]` covering three
 * groups (Contact / Lead / Transition) and two field types (enum +
 * currency). The enum resolver is mocked to return a fixed list of
 * pipeline stages; the tests assert grouping, lazy fetch, cache
 * behaviour, op-filter correctness, and sentence preview text.
 */

const STAGE_OPTIONS: EnumOption[] = [
  { value: 'new', label: 'New' },
  { value: 'won', label: 'Won' },
];

function fieldSpec(overrides: Partial<FieldSpec>): FieldSpec {
  return {
    path: 'unset',
    label: 'Unset',
    type: 'text',
    group: 'Contact',
    enum_resolver: null,
    help_text: null,
    ...overrides,
  };
}

const FIXTURE_FIELDS: FieldSpec[] = [
  fieldSpec({ path: 'contact.email', label: 'Email', type: 'text', group: 'Contact' }),
  fieldSpec({ path: 'contact.phone', label: 'Phone', type: 'text', group: 'Contact' }),
  fieldSpec({
    path: 'lead.pipeline_stage',
    label: 'Stage',
    type: 'enum',
    group: 'Lead',
    enum_resolver: 'pipeline_stages',
  }),
  fieldSpec({ path: 'lead.budget', label: 'Budget', type: 'currency', group: 'Lead' }),
  fieldSpec({
    path: 'to_status',
    label: 'New stage',
    type: 'enum',
    group: 'Transition',
    enum_resolver: 'pipeline_stages',
  }),
];

interface BuilderProbe {
  groupedFields(): Array<{ group: string; options: readonly unknown[] }>;
  opChoicesFor(index: number): ReadonlyArray<{ value: string; label: string }>;
  rules(): Array<{ field: string; op: string; value: string }>;
  addRule(): void;
  onFieldChange(index: number, value: string): void;
  onOpChange(index: number, value: string): void;
  onValueChange(index: number, value: string): void;
  toggleConjunction(): void;
  sentencePreview(): string;
  valuePools(): Map<string, EnumOption[]>;
}

describe('ConditionBuilderComponent', () => {
  let apiSpy: jasmine.SpyObj<AutomationsApiService>;

  function makeFixture(
    conditionFields: FieldSpec[] = FIXTURE_FIELDS,
    eventType = 'lead.created',
  ): ComponentFixture<ConditionBuilderComponent> {
    apiSpy = jasmine.createSpyObj<AutomationsApiService>('AutomationsApiService', [
      'listFieldValues',
    ]);
    apiSpy.listFieldValues.and.returnValue(of(STAGE_OPTIONS));

    TestBed.configureTestingModule({
      imports: [ConditionBuilderComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AutomationsApiService, useValue: apiSpy },
      ],
    });

    const fixture = TestBed.createComponent(ConditionBuilderComponent);
    // Set inputs on the componentRef so signal inputs pick them up.
    fixture.componentRef.setInput('conditionFields', conditionFields);
    fixture.componentRef.setInput('eventType', eventType);
    fixture.componentRef.setInput('conditions', {});
    fixture.detectChanges();
    return fixture;
  }

  function probe(fixture: ComponentFixture<ConditionBuilderComponent>): BuilderProbe {
    return fixture.componentInstance as unknown as BuilderProbe;
  }

  it('groups fields under <optgroup> sections in preferred order', () => {
    const fixture = makeFixture();
    const groups = probe(fixture).groupedFields();
    const names = groups.map((g) => g.group);
    // Contact / Lead / Transition all appear in that order (matches GROUP_ORDER).
    expect(names).toEqual(['Contact', 'Lead', 'Transition']);
    // Within a group, options are alphabetical by label.
    expect(groups[0].options.length).toBe(2);
  });

  it('selecting an enum field fires the field-values API once and populates the value pool', () => {
    const fixture = makeFixture();
    const cmp = probe(fixture);
    cmp.addRule(); // seeded with contact.email (first field)
    cmp.onFieldChange(0, 'lead.pipeline_stage');
    expect(apiSpy.listFieldValues).toHaveBeenCalledOnceWith('lead.created', 'lead.pipeline_stage');
    const pool = cmp.valuePools().get('lead.created:lead.pipeline_stage');
    expect(pool).toEqual(STAGE_OPTIONS);
  });

  it('cache: selecting the same field twice fires the API only once', () => {
    const fixture = makeFixture();
    const cmp = probe(fixture);
    cmp.addRule();
    cmp.onFieldChange(0, 'lead.pipeline_stage');
    cmp.onFieldChange(0, 'contact.email');
    cmp.onFieldChange(0, 'lead.pipeline_stage');
    expect(apiSpy.listFieldValues).toHaveBeenCalledTimes(1);
  });

  it('switching the event clears the cache signal', () => {
    const fixture = makeFixture();
    const cmp = probe(fixture);
    cmp.addRule();
    cmp.onFieldChange(0, 'lead.pipeline_stage');
    expect(cmp.valuePools().size).toBe(1);
    // Event switch — cache clears via effect().
    fixture.componentRef.setInput('eventType', 'contact.created');
    fixture.detectChanges();
    expect(cmp.valuePools().size).toBe(0);
  });

  it('op dropdown filters by field type', () => {
    const cases: Array<[FieldSpecType, string, string[]]> = [
      ['text', 'contact.email', ['eq', 'ne', 'contains']],
      ['currency', 'lead.budget', ['gte', 'lte', 'gt']],
      ['enum', 'lead.pipeline_stage', ['eq', 'ne', 'in', 'not_in']],
    ];
    for (const [_type, path, expectedOps] of cases) {
      const fixture = makeFixture();
      const cmp = probe(fixture);
      cmp.addRule();
      cmp.onFieldChange(0, path);
      const ops = cmp.opChoicesFor(0).map((o) => o.value);
      for (const op of expectedOps) {
        expect(ops).withContext(`op ${op} missing for ${path}`).toContain(op);
      }
      // Text-specific op must NOT appear on currency / enum
      if (path !== 'contact.email') {
        expect(ops).withContext(`'contains' leaked into ${path}`).not.toContain('contains');
      }
      // Range op must NOT appear on text / enum
      if (path !== 'lead.budget') {
        expect(ops).withContext(`'gt' leaked into ${path}`).not.toContain('gt');
      }
    }
  });

  it('sentence preview renders enum label + AND joiner for two-rule combo', () => {
    const fixture = makeFixture();
    const cmp = probe(fixture);
    // Rule 1: Lead → Stage equals Won.
    cmp.addRule();
    cmp.onFieldChange(0, 'lead.pipeline_stage');
    cmp.onValueChange(0, 'won');
    // Rule 2: Lead → Budget at least 50000.
    cmp.addRule();
    cmp.onFieldChange(1, 'lead.budget');
    cmp.onOpChange(1, 'gte');
    cmp.onValueChange(1, '50000');
    const preview = cmp.sentencePreview();
    expect(preview).toContain("Lead's Stage equals");
    expect(preview).toContain('"Won"'); // resolved label, not raw "won"
    expect(preview).toContain('AND');
    expect(preview).toContain("Lead's Budget is at least");
    expect(preview).toContain('₹');
  });
});
