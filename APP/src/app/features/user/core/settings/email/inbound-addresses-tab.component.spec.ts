/**
 * Karma coverage for the Inbound Addresses tab (tasks/email-inbound-
 * forwarding Step 5). Pins:
 *
 *   * Empty state renders the wizard-launch CTA.
 *   * List row renders label + composed forwarding_address.
 *   * ``last_inbound_at`` renders as relative time ("just now", "Xh
 *     ago") rather than the raw ISO string.
 *   * Copy button writes the exact address to clipboard.
 *   * Auto-create-contact toggle PATCHes the endpoint with the
 *     inverted value.
 *   * Deactivate + Delete actions confirm via ``window.confirm``
 *     before firing the API call.
 *   * "Add forwarding address" button triggers the wizard-launch
 *     path (shown via a toast until Step 6 lands the wizard).
 */
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { InboundAddressesTabComponent } from './inbound-addresses-tab.component';
import { InboundAddressesService } from './inbound-addresses.service';
import type { ForwardedAddress } from './models';

function makeRow(overrides: Partial<ForwardedAddress> = {}): ForwardedAddress {
  return {
    id: 'ep-1',
    label: 'Support inbox',
    forwarding_address: 'f-tok12345678@reply.example.com',
    auto_create_contact: true,
    default_assignee: null,
    is_active: true,
    last_inbound_at: null,
    created_at: '2026-09-21T00:00:00Z',
    ...overrides,
  };
}

describe('InboundAddressesTabComponent', () => {
  let apiSpy: jasmine.SpyObj<InboundAddressesService>;
  let toastSpy: jasmine.SpyObj<ToastService>;

  function makeFixture(rows: ForwardedAddress[]): ComponentFixture<InboundAddressesTabComponent> {
    apiSpy = jasmine.createSpyObj<InboundAddressesService>('InboundAddressesService', [
      'list',
      'create',
      'update',
      'deactivate',
      'remove',
    ]);
    apiSpy.list.and.returnValue(of(rows));
    toastSpy = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error', 'info']);

    TestBed.configureTestingModule({
      imports: [InboundAddressesTabComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: InboundAddressesService, useValue: apiSpy },
        { provide: ToastService, useValue: toastSpy },
      ],
    });
    const fixture = TestBed.createComponent(InboundAddressesTabComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('list_renders_all_forwarded_address_endpoints', () => {
    const rows: ForwardedAddress[] = [
      makeRow({ id: 'a', label: 'Alpha' }),
      makeRow({ id: 'b', label: 'Beta' }),
    ];
    const fixture = makeFixture(rows);
    const cards = fixture.nativeElement.querySelectorAll('[data-testid="inbound-row"]');
    expect(cards.length).toBe(2);
    expect(fixture.nativeElement.textContent).toContain('Alpha');
    expect(fixture.nativeElement.textContent).toContain('Beta');
  });

  it('list_shows_last_inbound_at_relative_time', () => {
    const rows: ForwardedAddress[] = [
      makeRow({ last_inbound_at: null }),
      makeRow({
        id: 'ep-2',
        last_inbound_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
      }),
    ];
    const fixture = makeFixture(rows);
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('No mail yet');
    expect(text).toContain('5m ago');
  });

  it('list_copy_button_copies_forwarding_address', async () => {
    const written: string[] = [];
    Object.defineProperty(navigator, 'clipboard', {
      value: {
        writeText: (v: string) => {
          written.push(v);
          return Promise.resolve();
        },
      },
      configurable: true,
    });
    const fixture = makeFixture([makeRow()]);
    (
      fixture.nativeElement.querySelector('[data-testid="inbound-copy"]') as HTMLButtonElement
    ).click();
    await Promise.resolve();
    expect(written).toEqual(['f-tok12345678@reply.example.com']);
  });

  it('list_auto_create_toggle_patches_endpoint', () => {
    const initial = makeRow({ auto_create_contact: true });
    const flipped: ForwardedAddress = { ...initial, auto_create_contact: false };
    const fixture = makeFixture([initial]);
    apiSpy.update.and.returnValue(of(flipped));

    const toggle = fixture.nativeElement.querySelector(
      '[data-testid="inbound-auto-create-toggle"]',
    ) as HTMLInputElement;
    toggle.click();
    fixture.detectChanges();

    expect(apiSpy.update).toHaveBeenCalledWith('ep-1', { auto_create_contact: false });
  });

  it('list_deactivate_button_confirms_before_call', () => {
    const fixture = makeFixture([makeRow()]);
    apiSpy.deactivate.and.returnValue(of(void 0 as unknown as void));

    spyOn(window, 'confirm').and.returnValue(false);
    (
      fixture.nativeElement.querySelector('[data-testid="inbound-deactivate"]') as HTMLButtonElement
    ).click();
    expect(apiSpy.deactivate).not.toHaveBeenCalled();

    (window.confirm as jasmine.Spy).and.returnValue(true);
    (
      fixture.nativeElement.querySelector('[data-testid="inbound-deactivate"]') as HTMLButtonElement
    ).click();
    expect(apiSpy.deactivate).toHaveBeenCalledWith('ep-1');
  });

  it('list_delete_button_shows_warning_before_confirm', () => {
    const fixture = makeFixture([makeRow()]);
    apiSpy.remove.and.returnValue(of(void 0 as unknown as void));

    const confirmSpy = spyOn(window, 'confirm').and.returnValue(false);
    (
      fixture.nativeElement.querySelector('[data-testid="inbound-delete"]') as HTMLButtonElement
    ).click();
    // The confirm text carries the warning verbatim.
    const promptShown = confirmSpy.calls.mostRecent().args[0] as string;
    expect(promptShown).toContain("won't reach the CRM");
    expect(apiSpy.remove).not.toHaveBeenCalled();
  });

  it('add_button_launches_wizard_placeholder', () => {
    const fixture = makeFixture([]);
    (
      fixture.nativeElement.querySelector('[data-testid="inbound-empty-cta"]') as HTMLButtonElement
    ).click();
    // Step 6 wires the actual wizard; until then a toast confirms
    // the click landed so the operator sees SOMETHING.
    expect(toastSpy.info).toHaveBeenCalled();
  });
});
