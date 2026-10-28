import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { RunHistoryPageComponent } from './run-history.page';
import { AutomationsApiService, RunRead, TriggerRead } from '../automations-api.service';
import { FurnitureAuthService } from '../../auth/auth.service';

function makeRun(overrides: Partial<RunRead> = {}): RunRead {
  return {
    id: 'run-1',
    org_id: 'org-1',
    trigger_id: 'trg-1',
    event_id: 'event-1',
    event_payload: { contact: { email: 'asha@x.com' } },
    contact_id: 'contact-1',
    user_id: null,
    status: 'failed',
    channel_message_id: null,
    error: 'SMTP timeout',
    scheduled_at: '2026-06-29T00:00:00Z',
    dispatched_at: '2026-06-29T00:00:05Z',
    completed_at: '2026-06-29T00:00:10Z',
    ...overrides,
  };
}

describe('RunHistoryPageComponent', () => {
  let apiSpy: jasmine.SpyObj<AutomationsApiService>;
  let authStub: { hasPermission: (k: string) => boolean };

  function makeFixture(rows: RunRead[] = []): ComponentFixture<RunHistoryPageComponent> {
    apiSpy = jasmine.createSpyObj<AutomationsApiService>('AutomationsApiService', [
      'get',
      'listRuns',
      'retry',
    ]);
    apiSpy.get.and.returnValue(
      of({
        id: 'trg-1',
        name: 'User Welcome',
      } as unknown as TriggerRead),
    );
    apiSpy.listRuns.and.returnValue(of({ items: rows, total: rows.length, limit: 50, offset: 0 }));
    apiSpy.retry.and.callFake((id: string) => of(makeRun({ id, status: 'queued', error: null })));

    authStub = { hasPermission: (_k: string) => true };

    const paramMap = {
      get: (key: string) => (key === 'id' ? 'trg-1' : null),
    };

    TestBed.configureTestingModule({
      imports: [RunHistoryPageComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AutomationsApiService, useValue: apiSpy },
        { provide: FurnitureAuthService, useValue: authStub },
        {
          provide: ActivatedRoute,
          useValue: { paramMap: of(paramMap) },
        },
      ],
    });

    const fixture = TestBed.createComponent(RunHistoryPageComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('renders the empty-state copy when no runs', () => {
    const fixture = makeFixture();
    const text: string = fixture.nativeElement.textContent ?? '';
    expect(text).toContain('No runs match your filters');
  });

  it('re-fetches with the right status filter on change', () => {
    const fixture = makeFixture([makeRun()]);
    apiSpy.listRuns.calls.reset();

    const cmp = fixture.componentInstance as unknown as {
      onStatusChange: (v: string) => void;
    };
    cmp.onStatusChange('failed');
    fixture.detectChanges();

    expect(apiSpy.listRuns).toHaveBeenCalled();
    const args = apiSpy.listRuns.calls.mostRecent().args[1];
    expect(args?.status).toBe('failed');
  });

  it('opens the retry modal only on failed runs and patches on success', () => {
    const failedRow = makeRun({ id: 'run-fail', status: 'failed' });
    const fixture = makeFixture([failedRow]);

    const cmp = fixture.componentInstance as unknown as {
      openRetry: (row: RunRead) => void;
      retryTarget: { (): RunRead | null };
      onRetried: (r: RunRead) => void;
      items: { (): RunRead[] };
    };
    cmp.openRetry(failedRow);
    expect(cmp.retryTarget()).toBe(failedRow);

    // Simulate the modal's success emit.
    cmp.onRetried(makeRun({ id: 'run-fail', status: 'queued', error: null }));
    expect(cmp.retryTarget()).toBeNull();
    expect(cmp.items()[0].status).toBe('queued');
    expect(cmp.items()[0].error).toBeNull();
  });
});
