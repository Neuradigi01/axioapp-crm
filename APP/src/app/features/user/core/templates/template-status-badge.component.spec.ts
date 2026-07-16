import { ComponentRef } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TemplateStatusBadgeComponent } from './template-status-badge.component';

/**
 * Campaigns v1 Step 02 — the rejection-reason tooltip.
 *
 * The badge only surfaces a tooltip when BOTH conditions hold:
 *   1. ``external`` input is ``'rejected'``.
 *   2. ``rejectionReason`` input is a non-empty string.
 *
 * Everything else (approved / pending / null / empty-string reason)
 * renders the plain non-interactive `<span>` — no tooltip, no
 * `cursor-help`, no `role="tooltip"` in the DOM.
 */

function tooltipEl(fixture: ComponentFixture<TemplateStatusBadgeComponent>): HTMLElement | null {
  return fixture.nativeElement.querySelector('[role="tooltip"]') as HTMLElement | null;
}

function badgeLabel(fixture: ComponentFixture<TemplateStatusBadgeComponent>): string {
  return (fixture.nativeElement.textContent ?? '').replace(/\s+/g, ' ').trim();
}

describe('TemplateStatusBadgeComponent — rejection reason tooltip', () => {
  let fixture: ComponentFixture<TemplateStatusBadgeComponent>;
  let ref: ComponentRef<TemplateStatusBadgeComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [TemplateStatusBadgeComponent],
    });
    fixture = TestBed.createComponent(TemplateStatusBadgeComponent);
    ref = fixture.componentRef;
  });

  it('renders no tooltip for an approved badge', () => {
    ref.setInput('external', 'approved');
    ref.setInput('rejectionReason', 'unused — approved rows never show the tooltip');
    fixture.detectChanges();
    expect(badgeLabel(fixture)).toContain('Provider approved');
    expect(tooltipEl(fixture)).toBeNull();
  });

  it('renders no tooltip for a pending badge', () => {
    ref.setInput('external', 'pending');
    ref.setInput('rejectionReason', null);
    fixture.detectChanges();
    expect(badgeLabel(fixture)).toContain('Pending review');
    expect(tooltipEl(fixture)).toBeNull();
  });

  it('renders no tooltip on a rejected badge when the reason is missing', () => {
    // Empty tooltips would be confusing — the badge falls back to the
    // plain non-interactive `<span>` when the reason isn't loaded yet.
    ref.setInput('external', 'rejected');
    ref.setInput('rejectionReason', null);
    fixture.detectChanges();
    expect(badgeLabel(fixture)).toContain('Provider rejected');
    expect(tooltipEl(fixture)).toBeNull();
  });

  it('renders no tooltip on a rejected badge when the reason is an empty string', () => {
    ref.setInput('external', 'rejected');
    ref.setInput('rejectionReason', '   ');
    fixture.detectChanges();
    expect(tooltipEl(fixture)).toBeNull();
  });

  it('renders the tooltip on a rejected badge with a real reason', () => {
    ref.setInput('external', 'rejected');
    ref.setInput('rejectionReason', 'Promotional wording violates policy.');
    fixture.detectChanges();

    const tooltip = tooltipEl(fixture);
    expect(tooltip).not.toBeNull();
    const text = tooltip!.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    expect(text).toContain('Meta rejection reason');
    expect(text).toContain('Promotional wording violates policy.');
    expect(text).toContain('Update the template and resubmit.');

    // Keyboard + screen-reader fallback: the badge carries a `title`
    // attribute mirroring the tooltip content. Users who can't hover
    // still get the reason via the native browser tooltip on focus.
    const groupEl = fixture.nativeElement.querySelector('span.group') as HTMLElement;
    expect(groupEl.getAttribute('title')).toContain('Promotional wording violates policy.');
  });

  it('leaves the internal-status branch alone (no rejection tooltip for internal statuses)', () => {
    ref.setInput('internal', 'draft');
    ref.setInput('rejectionReason', 'This should not surface');
    fixture.detectChanges();
    expect(badgeLabel(fixture)).toContain('Draft');
    expect(tooltipEl(fixture)).toBeNull();
  });
});
