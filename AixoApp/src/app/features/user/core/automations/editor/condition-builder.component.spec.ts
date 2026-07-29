import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import {
  AutomationsApiService,
  EnumOption,
  FieldSpec,
  FieldSpecType,
  PreviewMatchesResult,
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
  advancedMode(): boolean;
  toggleAdvancedMode(): void;
  ruleIsAdvanced(index: number): boolean;
  ruleIsLegacy(index: number): boolean;
  previewResult(): PreviewMatchesResult | null;
  previewLoading(): boolean;
  previewError(): boolean;
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

  // --- Step 4: legacy paths compatibility ----------------------------

  /**
   * Fixture: preload a trigger whose ``conditions`` reference a
   * field path (``lead.custom_widget_id``) not in the current
   * catalog. Builder must:
   *   * auto-engage Advanced mode so the row stays visible,
   *   * classify the row as Legacy (not Advanced),
   *   * preserve the AST byte-identically on a save-without-touch.
   */
  const LEGACY_AST = {
    field: 'lead.custom_widget_id',
    op: 'eq' as const,
    value: 'banner_v2',
  };

  function makeLegacyFixture(): ComponentFixture<ConditionBuilderComponent> {
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
    fixture.componentRef.setInput('conditionFields', FIXTURE_FIELDS);
    fixture.componentRef.setInput('eventType', 'lead.created');
    fixture.componentRef.setInput('conditions', LEGACY_AST);
    fixture.detectChanges();
    return fixture;
  }

  it('loading a trigger with a legacy path auto-engages Advanced mode', () => {
    const fixture = makeLegacyFixture();
    const cmp = probe(fixture);
    expect(cmp.advancedMode()).toBe(true);
    expect(cmp.rules().length).toBe(1);
    expect(cmp.ruleIsAdvanced(0)).toBe(true);
    expect(cmp.ruleIsLegacy(0)).toBe(true);
  });

  it('loading + saving a legacy trigger without touching it produces byte-identical conditions', () => {
    const fixture = makeLegacyFixture();
    const cmp = fixture.componentInstance;
    // The two-way `conditions` model was emitted at least once by
    // the hydrate effect — read it back and verify it's structurally
    // identical to the input. Byte-identical means every key + every
    // value + every type preserved (string stays string, number
    // stays number).
    const emitted = cmp.conditions();
    expect(emitted).toEqual(LEGACY_AST);
    // Property-key order preserved too (JSON.stringify catches
    // insertion-order drift for the byte-level assertion).
    expect(JSON.stringify(emitted)).toBe(JSON.stringify(LEGACY_AST));
  });

  it('mixes one standard and one legacy rule in a single trigger', () => {
    const mixedAst = {
      all: [
        { field: 'lead.pipeline_stage', op: 'eq' as const, value: 'won' },
        { field: 'lead.custom_widget_id', op: 'eq' as const, value: 'banner_v2' },
      ],
    };
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
    fixture.componentRef.setInput('conditionFields', FIXTURE_FIELDS);
    fixture.componentRef.setInput('eventType', 'lead.created');
    fixture.componentRef.setInput('conditions', mixedAst);
    fixture.detectChanges();
    const cmp = probe(fixture);
    expect(cmp.rules().length).toBe(2);
    expect(cmp.ruleIsLegacy(0)).toBe(false);
    expect(cmp.ruleIsAdvanced(0)).toBe(false);
    expect(cmp.ruleIsLegacy(1)).toBe(true);
    expect(cmp.ruleIsAdvanced(1)).toBe(true);
    // Save-without-touch preserves the whole tree.
    expect(fixture.componentInstance.conditions()).toEqual(mixedAst);
  });

  it('toggling Advanced off keeps legacy rules in the emitted AST', () => {
    const fixture = makeLegacyFixture();
    const cmp = probe(fixture);
    expect(cmp.advancedMode()).toBe(true);
    // Operator turns Advanced off — the UI stops showing the row
    // (verified via cmp.advancedMode() = false + template branch)
    // but the AST must still carry it so a save doesn't drop it.
    cmp.toggleAdvancedMode();
    expect(cmp.advancedMode()).toBe(false);
    expect(cmp.rules().length).toBe(1);
    expect(fixture.componentInstance.conditions()).toEqual(LEGACY_AST);
  });

  // --- Step 5: matched-events preview count --------------------------

  const PREVIEW_RUNS: PreviewMatchesResult = {
    matched: 3,
    scanned: 5,
    window_days: 7,
    source: 'runs',
    truncated: false,
  };

  it('debounces AST changes at 500ms then fires previewMatches once', fakeAsync(() => {
    const fixture = makeFixture();
    apiSpy.previewMatches = jasmine
      .createSpy<AutomationsApiService['previewMatches']>('previewMatches')
      .and.returnValue(of(PREVIEW_RUNS));
    const cmp = probe(fixture);
    // Simulate a fast typer — three AST mutations inside the
    // debounce window. Only the last should fire the endpoint.
    cmp.addRule();
    cmp.onFieldChange(0, 'lead.pipeline_stage');
    cmp.onValueChange(0, 'w');
    cmp.onValueChange(0, 'wo');
    cmp.onValueChange(0, 'won');
    tick(200);
    expect(apiSpy.previewMatches).not.toHaveBeenCalled();
    tick(500);
    expect(apiSpy.previewMatches).toHaveBeenCalledTimes(1);
    expect(cmp.previewResult()).toEqual(PREVIEW_RUNS);
    expect(cmp.previewLoading()).toBe(false);
  }));

  it('surfaces source="none" honestly (frontend renders "no historical events" hint)', fakeAsync(() => {
    const fixture = makeFixture();
    const noneResult: PreviewMatchesResult = {
      matched: 0,
      scanned: 0,
      window_days: 7,
      source: 'none',
      truncated: false,
    };
    apiSpy.previewMatches = jasmine
      .createSpy<AutomationsApiService['previewMatches']>('previewMatches')
      .and.returnValue(of(noneResult));
    const cmp = probe(fixture);
    cmp.addRule();
    cmp.onFieldChange(0, 'lead.pipeline_stage');
    cmp.onValueChange(0, 'won');
    tick(500);
    expect(cmp.previewResult()?.source).toBe('none');
    expect(cmp.previewError()).toBe(false);
  }));

  it('errors are swallowed into previewError so Save stays available', fakeAsync(() => {
    const fixture = makeFixture();
    apiSpy.previewMatches = jasmine
      .createSpy<AutomationsApiService['previewMatches']>('previewMatches')
      .and.returnValue(throwError(() => new Error('boom')));
    const cmp = probe(fixture);
    cmp.addRule();
    cmp.onFieldChange(0, 'lead.pipeline_stage');
    cmp.onValueChange(0, 'won');
    tick(500);
    expect(cmp.previewError()).toBe(true);
    expect(cmp.previewLoading()).toBe(false);
    expect(cmp.previewResult()).toBeNull();
  }));
});
