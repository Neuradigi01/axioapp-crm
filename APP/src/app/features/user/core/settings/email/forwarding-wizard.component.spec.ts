/**
 * Karma coverage for the 3-step forwarding wizard (tasks/email-
 * inbound-forwarding Step 6).
 *
 * Notes on step numbering: my implementation puts the "create the
 * endpoint" call at the transition from step 2 → 3, and the address
 * + copy button + guide + polling all render together on step 3.
 * Test names refer to the step where each behaviour SURFACES to the
 * operator — not the spec's aspirational step-2/step-3 split.
 */
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { Subject, of } from 'rxjs';

import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { ForwardingWizardComponent } from './forwarding-wizard.component';
import { InboundAddressesService } from './inbound-addresses.service';
import type { ForwardedAddress } from './models';
import {
  POLL_CEILING_MS,
  POLL_INTERVAL_MS,
  TestInboundStatusService,
  type PollTick,
} from './test-inbound-status.service';

function makeAddress(overrides: Partial<ForwardedAddress> = {}): ForwardedAddress {
  return {
    id: 'ep-created-1',
    label: 'Support inbox — Gmail (personal)',
    forwarding_address: 'f-tok12345678@reply.example.com',
    auto_create_contact: true,
    default_assignee: null,
    is_active: true,
    last_inbound_at: null,
    created_at: '2026-09-21T00:00:00Z',
    ...overrides,
  };
}

describe('ForwardingWizardComponent', () => {
  let apiSpy: jasmine.SpyObj<InboundAddressesService>;
  let pollSpy: jasmine.SpyObj<TestInboundStatusService>;
  let toastSpy: jasmine.SpyObj<ToastService>;
  let pollSubject: Subject<PollTick>;

  function makeFixture(): ComponentFixture<ForwardingWizardComponent> {
    apiSpy = jasmine.createSpyObj<InboundAddressesService>('InboundAddressesService', [
      'create',
      'list',
      'update',
      'deactivate',
      'remove',
    ]);
    pollSpy = jasmine.createSpyObj<TestInboundStatusService>('TestInboundStatusService', [
      'fetchOnce',
      'poll',
    ]);
    pollSubject = new Subject<PollTick>();
    pollSpy.poll.and.returnValue(pollSubject.asObservable());
    toastSpy = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error', 'info']);

    TestBed.configureTestingModule({
      imports: [ForwardingWizardComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: InboundAddressesService, useValue: apiSpy },
        { provide: TestInboundStatusService, useValue: pollSpy },
        { provide: ToastService, useValue: toastSpy },
      ],
    });

    const fixture = TestBed.createComponent(ForwardingWizardComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('step1_renders_6_provider_cards', () => {
    const fixture = makeFixture();
    const cards = fixture.nativeElement.querySelectorAll('[data-testid^="wizard-provider-"]');
    expect(cards.length).toBe(6);
  });

  it('step1_click_provider_advances_to_step2', () => {
    const fixture = makeFixture();
    (
      fixture.nativeElement.querySelector(
        '[data-testid="wizard-provider-gmail"]',
      ) as HTMLButtonElement
    ).click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-testid="wizard-step-2"]')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('[data-testid="wizard-step-1"]')).toBeNull();
  });

  it('step2_requires_label_before_advance', () => {
    const fixture = makeFixture();
    (
      fixture.nativeElement.querySelector(
        '[data-testid="wizard-provider-gmail"]',
      ) as HTMLButtonElement
    ).click();
    fixture.detectChanges();

    // Clear the pre-filled label; Next should be disabled.
    const label = fixture.nativeElement.querySelector(
      '[data-testid="wizard-label"]',
    ) as HTMLInputElement;
    label.value = '';
    label.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    const next = fixture.nativeElement.querySelector(
      '[data-testid="wizard-next"]',
    ) as HTMLButtonElement;
    expect(next.disabled).toBeTrue();
    expect(apiSpy.create).not.toHaveBeenCalled();
  });

  it('step3_shows_forwarding_address_with_copy_button_after_create', () => {
    const fixture = makeFixture();
    apiSpy.create.and.returnValue(of(makeAddress()));

    (
      fixture.nativeElement.querySelector(
        '[data-testid="wizard-provider-gmail"]',
      ) as HTMLButtonElement
    ).click();
    fixture.detectChanges();
    (
      fixture.nativeElement.querySelector('[data-testid="wizard-next"]') as HTMLButtonElement
    ).click();
    fixture.detectChanges();

    const address = fixture.nativeElement.querySelector('[data-testid="wizard-address"]');
    expect(address).not.toBeNull();
    expect(address.textContent).toContain('f-tok12345678@reply.example.com');
    expect(fixture.nativeElement.querySelector('[data-testid="wizard-copy"]')).not.toBeNull();
    expect(apiSpy.create).toHaveBeenCalledOnceWith({
      label: 'Support inbox — Gmail (personal)',
      auto_create_contact: true,
    });
  });

  it('step3_renders_provider_specific_steps_verbatim', () => {
    const fixture = makeFixture();
    apiSpy.create.and.returnValue(of(makeAddress()));

    (
      fixture.nativeElement.querySelector(
        '[data-testid="wizard-provider-gmail"]',
      ) as HTMLButtonElement
    ).click();
    fixture.detectChanges();
    (
      fixture.nativeElement.querySelector('[data-testid="wizard-next"]') as HTMLButtonElement
    ).click();
    fixture.detectChanges();

    const stepsList = fixture.nativeElement.querySelector('[data-testid="wizard-steps"]');
    expect(stepsList).not.toBeNull();
    // First Gmail step from provider-guides.ts — pinned verbatim.
    expect(stepsList.textContent).toContain('Forwarding and POP/IMAP');
  });

  it('step3_polls_test_inbound_status_at_5s_interval', () => {
    const fixture = makeFixture();
    apiSpy.create.and.returnValue(of(makeAddress()));

    (
      fixture.nativeElement.querySelector(
        '[data-testid="wizard-provider-gmail"]',
      ) as HTMLButtonElement
    ).click();
    fixture.detectChanges();
    (
      fixture.nativeElement.querySelector('[data-testid="wizard-next"]') as HTMLButtonElement
    ).click();
    fixture.detectChanges();

    // Assert the polling service was subscribed to for THIS endpoint.
    expect(pollSpy.poll).toHaveBeenCalledOnceWith('ep-created-1');
    // Sanity — the exported cadence is what the wizard subscribes to.
    expect(POLL_INTERVAL_MS).toBe(5_000);
  });

  it('step3_success_after_bump_shows_confirm_state', () => {
    const fixture = makeFixture();
    apiSpy.create.and.returnValue(of(makeAddress()));

    (
      fixture.nativeElement.querySelector(
        '[data-testid="wizard-provider-gmail"]',
      ) as HTMLButtonElement
    ).click();
    fixture.detectChanges();
    (
      fixture.nativeElement.querySelector('[data-testid="wizard-next"]') as HTMLButtonElement
    ).click();
    fixture.detectChanges();

    // Simulate the poll stream emitting a ``received`` tick.
    pollSubject.next({ kind: 'received', last_inbound_at: '2026-09-21T01:23:45Z' });
    fixture.detectChanges();

    expect(
      fixture.nativeElement.querySelector('[data-testid="wizard-badge-received"]'),
    ).not.toBeNull();
    expect(fixture.nativeElement.querySelector('[data-testid="wizard-badge-waiting"]')).toBeNull();
    // "Done" button shows in the received state.
    expect(
      (fixture.nativeElement.querySelector('[data-testid="wizard-done"]') as HTMLButtonElement)
        .textContent,
    ).toContain('Done');
  });

  it('step3_timeout_shows_recheck_prompt', () => {
    const fixture = makeFixture();
    apiSpy.create.and.returnValue(of(makeAddress()));

    (
      fixture.nativeElement.querySelector(
        '[data-testid="wizard-provider-gmail"]',
      ) as HTMLButtonElement
    ).click();
    fixture.detectChanges();
    (
      fixture.nativeElement.querySelector('[data-testid="wizard-next"]') as HTMLButtonElement
    ).click();
    fixture.detectChanges();

    pollSubject.next({ kind: 'timeout' });
    fixture.detectChanges();

    const badge = fixture.nativeElement.querySelector(
      '[data-testid="wizard-badge-timeout"]',
    ) as HTMLElement | null;
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toContain('Not received');
    // Ceiling matches the exported constant (5 min).
    expect(POLL_CEILING_MS).toBe(5 * 60 * 1000);
  });

  it('close_before_test_completes_still_creates_endpoint', () => {
    const fixture = makeFixture();
    const created = makeAddress();
    apiSpy.create.and.returnValue(of(created));

    (
      fixture.nativeElement.querySelector(
        '[data-testid="wizard-provider-gmail"]',
      ) as HTMLButtonElement
    ).click();
    fixture.detectChanges();
    (
      fixture.nativeElement.querySelector('[data-testid="wizard-next"]') as HTMLButtonElement
    ).click();
    fixture.detectChanges();

    // Endpoint exists; user closes before receiving a test.
    let closedEvents = 0;
    fixture.componentInstance.closed.subscribe(() => closedEvents++);

    (
      fixture.nativeElement.querySelector('[data-testid="wizard-close"]') as HTMLButtonElement
    ).click();
    fixture.detectChanges();

    expect(apiSpy.create).toHaveBeenCalled();
    expect(closedEvents).toBe(1);
  });

  it('step3_copy_button_writes_forwarding_address_to_clipboard', fakeAsync(() => {
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

    const fixture = makeFixture();
    apiSpy.create.and.returnValue(of(makeAddress()));

    (
      fixture.nativeElement.querySelector(
        '[data-testid="wizard-provider-gmail"]',
      ) as HTMLButtonElement
    ).click();
    fixture.detectChanges();
    (
      fixture.nativeElement.querySelector('[data-testid="wizard-next"]') as HTMLButtonElement
    ).click();
    fixture.detectChanges();

    (
      fixture.nativeElement.querySelector('[data-testid="wizard-copy"]') as HTMLButtonElement
    ).click();
    tick();
    expect(written).toEqual(['f-tok12345678@reply.example.com']);
  }));
});
