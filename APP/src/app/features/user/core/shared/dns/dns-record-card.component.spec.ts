/**
 * Karma coverage for the shared DNS-record card (tasks/email-sending-
 * domains Step 7). Pins two rules the parent tabs (Sending Domains
 * now, Custom Inbound Domain later) both rely on:
 *
 *   1. The Priority column renders **only** for MX records — other
 *      record types (TXT for SPF/DKIM/DMARC) have no priority, and
 *      showing a stray column would confuse the operator.
 *   2. The copy button copies the record VALUE verbatim, byte-for-
 *      byte, so the operator can paste it into their DNS provider
 *      without stripping whitespace or re-typing.
 */
import { ComponentRef } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import type { DnsRecord } from '../../settings/email/models';
import { DnsRecordCardComponent } from './dns-record-card.component';

function makeRecord(overrides: Partial<DnsRecord> = {}): DnsRecord {
  return {
    record_type: 'TXT',
    name: '_dmarc.example.com',
    value: 'v=DMARC1; p=none;',
    priority: null,
    valid: 'unknown',
    cached: [],
    is_active: true,
    ...overrides,
  };
}

describe('DnsRecordCardComponent', () => {
  let fixture: ComponentFixture<DnsRecordCardComponent>;
  let ref: ComponentRef<DnsRecordCardComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [DnsRecordCardComponent],
    });
    fixture = TestBed.createComponent(DnsRecordCardComponent);
    ref = fixture.componentRef;
  });

  it('renders_priority_column_only_for_mx_records', () => {
    ref.setInput('record', makeRecord({ record_type: 'TXT', priority: null }));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-testid="dns-record-priority"]')).toBeNull();

    ref.setInput(
      'record',
      makeRecord({
        record_type: 'MX',
        name: 'example.com',
        value: 'mxa.mailgun.org',
        priority: '10',
      }),
    );
    fixture.detectChanges();
    const priorityEl = fixture.nativeElement.querySelector(
      '[data-testid="dns-record-priority"]',
    ) as HTMLElement | null;
    expect(priorityEl).not.toBeNull();
    expect(priorityEl!.textContent).toContain('10');
  });

  it('copy_button_copies_record_value_exact', async () => {
    const written: string[] = [];
    // ``navigator.clipboard.writeText`` isn't available in jsdom by
    // default — stub it so we can capture the payload byte-for-byte.
    Object.defineProperty(navigator, 'clipboard', {
      value: {
        writeText: (text: string) => {
          written.push(text);
          return Promise.resolve();
        },
      },
      configurable: true,
    });

    const exactValue = 'v=DMARC1; p=none; rua=mailto:dmarc@yourshop.com';
    ref.setInput(
      'record',
      makeRecord({
        record_type: 'TXT',
        name: '_dmarc.yourshop.com',
        value: exactValue,
      }),
    );
    fixture.detectChanges();

    const copyBtn = fixture.nativeElement.querySelector(
      '[data-testid="dns-record-copy-value"]',
    ) as HTMLButtonElement | null;
    expect(copyBtn).not.toBeNull();

    copyBtn!.click();
    // clipboard.writeText is async; drain the microtask.
    await Promise.resolve();

    expect(written).toEqual([exactValue]);
  });
});
