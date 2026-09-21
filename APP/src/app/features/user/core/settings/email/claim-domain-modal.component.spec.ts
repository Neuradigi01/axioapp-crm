/**
 * Karma coverage for the claim-domain modal (tasks/email-sending-
 * domains Step 7). Pins the two client-side gates that stop the modal
 * from POSTing a bad payload:
 *
 *   * inline invalid-domain banner appears once the field is touched
 *     and the ``hostnameApex`` validator rejects.
 *   * scheme-prefixed URLs (``https://foo.com``) are rejected before
 *     ``submit()`` fires — the modal never emits ``submitted``.
 */
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ClaimDomainModalComponent } from './claim-domain-modal.component';

describe('ClaimDomainModalComponent', () => {
  let fixture: ComponentFixture<ClaimDomainModalComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [ClaimDomainModalComponent],
    });
    fixture = TestBed.createComponent(ClaimDomainModalComponent);
    fixture.detectChanges();
  });

  it('claim_modal_validates_domain_inline', () => {
    const input = fixture.nativeElement.querySelector(
      '[data-testid="claim-domain-input"]',
    ) as HTMLInputElement;
    expect(input).not.toBeNull();
    // Type an invalid domain and touch the field.
    input.value = 'not a domain';
    input.dispatchEvent(new Event('input'));
    input.dispatchEvent(new Event('blur'));
    fixture.detectChanges();
    expect(
      fixture.nativeElement.querySelector('[data-testid="claim-domain-error"]'),
    ).not.toBeNull();
  });

  it('claim_modal_rejects_scheme_urls_pre_submit', () => {
    const emitted: unknown[] = [];
    fixture.componentInstance.submitted.subscribe((v) => emitted.push(v));

    const input = fixture.nativeElement.querySelector(
      '[data-testid="claim-domain-input"]',
    ) as HTMLInputElement;
    input.value = 'https://foo.com';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    const submit = fixture.nativeElement.querySelector(
      '[data-testid="claim-domain-submit"]',
    ) as HTMLButtonElement;
    // The submit button is disabled while the form is invalid — clicking
    // it programmatically still triggers the form-submit handler, but
    // the guard in ``submit()`` bails without emitting.
    submit.click();
    fixture.detectChanges();

    expect(emitted).toEqual([]);
  });
});
