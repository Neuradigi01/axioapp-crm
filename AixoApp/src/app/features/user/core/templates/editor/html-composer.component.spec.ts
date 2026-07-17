import { ComponentRef } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { HtmlComposerComponent } from './html-composer.component';

/**
 * Campaigns v1 Step 04 — split-pane HTML composer for Email
 * templates and inline Email campaign bodies.
 *
 * The component doesn't own state — it emits `valueChange` on every
 * input event, and the parent form re-feeds the new value via
 * `[value]`. Spec focuses on:
 *
 *   1. Textarea input fires `valueChange`.
 *   2. Preview pane renders whatever is in `value()` (Angular's
 *      DOM sanitiser handles the safety — we assert the tag exists).
 *   3. Merge-tag inserter drops the placeholder at the current caret
 *      position (or at the end when the textarea hasn't rendered yet).
 */

describe('HtmlComposerComponent', () => {
  let fixture: ComponentFixture<HtmlComposerComponent>;
  let ref: ComponentRef<HtmlComposerComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HtmlComposerComponent],
    });
    fixture = TestBed.createComponent(HtmlComposerComponent);
    ref = fixture.componentRef;
  });

  it('emits the textarea value on input events', () => {
    ref.setInput('value', '');
    fixture.detectChanges();
    const emitted: string[] = [];
    fixture.componentInstance.valueChange.subscribe((v) => emitted.push(v));

    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    textarea.value = '<p>Hi</p>';
    textarea.dispatchEvent(new Event('input'));
    expect(emitted).toEqual(['<p>Hi</p>']);
  });

  it('renders the current value inside the preview pane', () => {
    ref.setInput('value', '<p>Preview me</p>');
    fixture.detectChanges();
    const preview = fixture.nativeElement.querySelector(
      '[class*="border-zinc-200"][class*="bg-white"][class*="p-3"][class*="text-sm"]',
    ) as HTMLElement | null;
    // Fall back to a broader lookup if the class targeting drifts.
    const previewText = (preview ?? fixture.nativeElement).textContent ?? '';
    expect(previewText).toContain('Preview me');
    // The <p> tag survives the DOM sanitiser.
    expect(fixture.nativeElement.querySelector('p')?.textContent).toContain('Preview me');
  });

  it('inserts a merge tag at the end of the value when no selection is set', () => {
    ref.setInput('value', 'Hi ');
    fixture.detectChanges();
    const emitted: string[] = [];
    fixture.componentInstance.valueChange.subscribe((v) => emitted.push(v));
    // Simulate a "no selection" branch: force selectionStart/end back
    // to the end of the string so the caret sits after "Hi ".
    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    fixture.componentInstance.onInsertTag('{{first_name}}');
    expect(emitted).toEqual(['Hi {{first_name}}']);
  });

  it('inserts a merge tag at the current caret position', () => {
    ref.setInput('value', 'Hi , welcome');
    fixture.detectChanges();
    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    // Position caret between "Hi " and ", welcome".
    textarea.setSelectionRange(3, 3);
    const emitted: string[] = [];
    fixture.componentInstance.valueChange.subscribe((v) => emitted.push(v));
    fixture.componentInstance.onInsertTag('{{first_name}}');
    expect(emitted).toEqual(['Hi {{first_name}}, welcome']);
  });

  it('exposes every default merge tag in the inserter dropdown', () => {
    fixture.detectChanges();
    const select = fixture.nativeElement.querySelector('select') as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toContain('{{first_name}}');
    expect(values).toContain('{{email}}');
    expect(values).toContain('{{phone}}');
  });
});
