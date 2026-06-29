import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { AutomationsPageComponent } from './automations.page';
import {
  AutomationsApiService,
  TriggerRead,
} from './automations-api.service';
import { FurnitureAuthService } from '../auth/auth.service';


function makeTrigger(overrides: Partial<TriggerRead> = {}): TriggerRead {
  return {
    id: 'trg-1',
    org_id: 'org-1',
    name: 'User Welcome',
    event_type: 'user.signed_up',
    channel: 'email',
    template_id: 'tpl-1',
    enabled: true,
    conditions: {},
    delay_seconds: 0,
    recipient_resolver: 'user.email',
    recipient_resolver_config: {},
    created_by_user_id: null,
    updated_by_user_id: null,
    created_at: '2026-06-29T00:00:00Z',
    updated_at: '2026-06-29T00:00:00Z',
    ...overrides,
  };
}


describe('AutomationsPageComponent', () => {
  let apiSpy: jasmine.SpyObj<AutomationsApiService>;
  let authStub: { hasPermission: (k: string) => boolean };

  function makeFixture(
    initialRows: TriggerRead[] = [],
  ): ComponentFixture<AutomationsPageComponent> {
    apiSpy = jasmine.createSpyObj<AutomationsApiService>(
      'AutomationsApiService',
      ['list', 'listEventTypes', 'enable', 'disable'],
    );
    apiSpy.list.and.returnValue(
      of({
        items: initialRows,
        total: initialRows.length,
        limit: 25,
        offset: 0,
      }),
    );
    apiSpy.listEventTypes.and.returnValue(of([]));
    apiSpy.enable.and.callFake((id: string) =>
      of(makeTrigger({ id, enabled: true })),
    );
    apiSpy.disable.and.callFake((id: string) =>
      of(makeTrigger({ id, enabled: false })),
    );

    authStub = { hasPermission: (_k: string) => true };

    TestBed.configureTestingModule({
      imports: [AutomationsPageComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AutomationsApiService, useValue: apiSpy },
        { provide: FurnitureAuthService, useValue: authStub },
      ],
    });

    const fixture = TestBed.createComponent(AutomationsPageComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('renders the empty-state copy when the API returns no triggers', () => {
    const fixture = makeFixture();
    const text: string = fixture.nativeElement.textContent ?? '';
    expect(text).toContain('No automations match your filters.');
  });

  it('toggling an enabled trigger calls /disable and updates the row', () => {
    const seeded = makeTrigger({ enabled: true });
    const fixture = makeFixture([seeded]);

    const cmp = fixture.componentInstance as unknown as {
      onToggleEnabled: (row: TriggerRead) => void;
      items: { (): TriggerRead[] };
    };
    cmp.onToggleEnabled(seeded);
    fixture.detectChanges();

    expect(apiSpy.disable).toHaveBeenCalledWith('trg-1');
    expect(cmp.items()[0].enabled).toBe(false);
  });

  it('re-fetches with the right channel filter on change', () => {
    const fixture = makeFixture();
    apiSpy.list.calls.reset();

    const cmp = fixture.componentInstance as unknown as {
      onChannelChange: (v: string) => void;
    };
    cmp.onChannelChange('whatsapp');
    fixture.detectChanges();

    expect(apiSpy.list).toHaveBeenCalled();
    const args = apiSpy.list.calls.mostRecent().args[0];
    expect(args?.channel).toBe('whatsapp');
  });
});
