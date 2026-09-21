/**
 * Karma coverage for the Sending Domains tab (tasks/email-sending-
 * domains Step 7).
 *
 * Pins:
 *   * Empty state renders the "Claim your domain" CTA when the API
 *     returns no rows.
 *   * DNS records land verbatim from the ``dns_records`` blob (Mailgun
 *     shape) into the expanded records panel.
 *   * Clicking "Check now" invokes ``verify()`` on the service and the
 *     row's status refreshes.
 *   * A demoted row surfaces the amber standard-warning banner.
 */
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ToastService } from '../../../../../shared/components/toast/toast.service';
import type { SendingDomain } from './models';
import { SendingDomainsService } from './sending-domains.service';
import { SendingDomainsTabComponent } from './sending-domains-tab.component';

function makeDomain(overrides: Partial<SendingDomain> = {}): SendingDomain {
  return {
    id: 'id-1',
    domain: 'yourshop.com',
    verification_status: 'pending',
    dns_records: {
      sending: [
        {
          record_type: 'TXT',
          name: 'smtp._domainkey.yourshop.com',
          value: 'v=DKIM1; k=rsa; p=MIIB...',
          priority: null,
          valid: 'unknown',
          cached: [],
          is_active: true,
        },
      ],
      receiving: [
        {
          record_type: 'MX',
          name: 'yourshop.com',
          value: 'mxa.mailgun.org',
          priority: '10',
          valid: 'unknown',
          cached: [],
          is_active: true,
        },
      ],
    },
    mx_verified: false,
    spf_verified: false,
    dkim_verified: false,
    dmarc_verified: false,
    last_verified_at: null,
    region: 'us',
    created_at: '2026-09-21T00:00:00Z',
    ...overrides,
  };
}

describe('SendingDomainsTabComponent', () => {
  let apiSpy: jasmine.SpyObj<SendingDomainsService>;
  let toastSpy: jasmine.SpyObj<ToastService>;

  function makeFixture(rows: SendingDomain[]): ComponentFixture<SendingDomainsTabComponent> {
    apiSpy = jasmine.createSpyObj<SendingDomainsService>('SendingDomainsService', [
      'list',
      'claim',
      'verify',
      'release',
    ]);
    apiSpy.list.and.returnValue(of(rows));
    toastSpy = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error', 'info']);

    TestBed.configureTestingModule({
      imports: [SendingDomainsTabComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: SendingDomainsService, useValue: apiSpy },
        { provide: ToastService, useValue: toastSpy },
      ],
    });

    const fixture = TestBed.createComponent(SendingDomainsTabComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('empty_state_shows_claim_cta', () => {
    const fixture = makeFixture([]);
    const empty = fixture.nativeElement.querySelector(
      '[data-testid="sending-domains-empty"]',
    ) as HTMLElement | null;
    expect(empty).not.toBeNull();
    expect(
      fixture.nativeElement.querySelector('[data-testid="sending-domains-empty-cta"]'),
    ).not.toBeNull();
  });

  it('domains_tab_renders_dns_records_from_jsonb_verbatim', () => {
    const row = makeDomain();
    const fixture = makeFixture([row]);

    // Expand records panel.
    (
      fixture.nativeElement.querySelector(
        '[data-testid="sending-domain-toggle-records"]',
      ) as HTMLButtonElement
    ).click();
    fixture.detectChanges();

    const panel = fixture.nativeElement.querySelector(
      '[data-testid="sending-domain-records-panel"]',
    ) as HTMLElement | null;
    expect(panel).not.toBeNull();
    // Values from the JSONB blob appear verbatim (no re-templating).
    const valueEls = panel!.querySelectorAll('[data-testid="dns-record-value"]');
    const rendered = Array.from(valueEls).map((el) => (el.textContent ?? '').trim());
    expect(rendered).toContain('v=DKIM1; k=rsa; p=MIIB...');
    expect(rendered).toContain('mxa.mailgun.org');
  });

  it('domains_tab_check_now_button_triggers_verify_and_refreshes_row', () => {
    const row = makeDomain();
    const updated = makeDomain({
      verification_status: 'verified',
      last_verified_at: new Date().toISOString(),
    });
    const fixture = makeFixture([row]);
    apiSpy.verify.and.returnValue(of(updated));

    (
      fixture.nativeElement.querySelector(
        '[data-testid="sending-domain-check-now"]',
      ) as HTMLButtonElement
    ).click();
    fixture.detectChanges();

    expect(apiSpy.verify).toHaveBeenCalledWith('id-1');
    // Card reflects the new verified status.
    const card = fixture.nativeElement.querySelector(
      '[data-testid="sending-domain-card"]',
    ) as HTMLElement;
    expect(card.getAttribute('data-status')).toBe('verified');
  });

  it('domains_tab_demoted_domain_shows_amber_warning_banner', () => {
    const row = makeDomain({ verification_status: 'demoted' });
    const fixture = makeFixture([row]);
    const banner = fixture.nativeElement.querySelector(
      '[data-testid="sending-domain-demoted-banner"]',
    ) as HTMLElement | null;
    expect(banner).not.toBeNull();
    // Standard amber banner class combo (memory
    // ``feedback_standard_warning_banner_pattern``).
    expect(banner!.className).toContain('border-amber-500/20');
    expect(banner!.className).toContain('bg-amber-500/10');
    expect(banner!.className).toContain('text-amber-400');
  });
});
