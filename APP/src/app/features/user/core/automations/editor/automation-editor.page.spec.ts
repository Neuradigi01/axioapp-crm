import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { AutomationEditorPageComponent } from './automation-editor.page';
import { AutomationsApiService, TriggerRead } from '../automations-api.service';
import { TemplateRead, TemplatesApiService } from '../../templates/templates-api.service';
import { FurnitureAuthService } from '../../auth/auth.service';

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

describe('AutomationEditorPageComponent', () => {
  let apiSpy: jasmine.SpyObj<AutomationsApiService>;
  let templatesSpy: jasmine.SpyObj<TemplatesApiService>;
  let authStub: { hasPermission: (k: string) => boolean };

  function makeFixture(
    opts: {
      triggerId?: string;
      initialTrigger?: TriggerRead;
    } = {},
  ): ComponentFixture<AutomationEditorPageComponent> {
    apiSpy = jasmine.createSpyObj<AutomationsApiService>('AutomationsApiService', [
      'get',
      'create',
      'update',
      'listEventTypes',
      'dryRun',
    ]);
    apiSpy.listEventTypes.and.returnValue(
      of([
        {
          event_type: 'user.signed_up',
          label: 'User signed up',
          description: 'A new Owner finishes self-signup.',
          sample_payload: {
            user: { full_name: 'Asha', email: 'asha@x.com' },
          },
        },
        {
          event_type: 'lead.created',
          label: 'Lead created',
          description: 'New lead from any source.',
          sample_payload: {
            contact: { full_name: 'Asha', email: 'asha@x.com' },
            source: 'widget',
          },
        },
      ]),
    );
    apiSpy.get.and.returnValue(of(opts.initialTrigger ?? makeTrigger()));
    apiSpy.create.and.returnValue(of(makeTrigger()));
    apiSpy.update.and.returnValue(of(makeTrigger()));
    apiSpy.dryRun.and.returnValue(
      of({
        would_match: true,
        skip_reason: null,
        would_send_to: 'asha@x.com',
        rendered_subject: 'Welcome',
        rendered_body: 'Hi Asha',
      }),
    );

    templatesSpy = jasmine.createSpyObj<TemplatesApiService>('TemplatesApiService', [
      'get',
      'list',
    ]);
    templatesSpy.get.and.returnValue(
      of({
        id: 'tpl-1',
        name: 'User Welcome',
      } as unknown as TemplateRead),
    );
    templatesSpy.list.and.returnValue(of({ items: [], total: 0, limit: 100, offset: 0 }));

    authStub = { hasPermission: (_k: string) => true };

    const paramMap = {
      get: (key: string) => (key === 'id' ? (opts.triggerId ?? null) : null),
    };

    TestBed.configureTestingModule({
      imports: [AutomationEditorPageComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AutomationsApiService, useValue: apiSpy },
        { provide: TemplatesApiService, useValue: templatesSpy },
        { provide: FurnitureAuthService, useValue: authStub },
        {
          provide: ActivatedRoute,
          useValue: { paramMap: of(paramMap) },
        },
      ],
    });

    const fixture = TestBed.createComponent(AutomationEditorPageComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('loads an existing trigger and populates the form', () => {
    const fixture = makeFixture({
      triggerId: 'trg-1',
      initialTrigger: makeTrigger({
        name: 'Welcome v2',
        event_type: 'user.signed_up',
        delay_seconds: 600,
      }),
    });
    const cmp = fixture.componentInstance as unknown as {
      form: {
        controls: {
          name: { value: string };
          event_type: { value: string };
          delay_seconds: { value: number };
        };
      };
    };
    fixture.detectChanges();
    expect(apiSpy.get).toHaveBeenCalledWith('trg-1');
    expect(cmp.form.controls.name.value).toBe('Welcome v2');
    expect(cmp.form.controls.event_type.value).toBe('user.signed_up');
    expect(cmp.form.controls.delay_seconds.value).toBe(600);
  });

  it('opens the template picker only after a channel is chosen', () => {
    const fixture = makeFixture();
    const cmp = fixture.componentInstance as unknown as {
      form: { controls: { channel: { setValue: (v: string) => void } } };
      pickerOpen: { (): boolean };
      openPicker: () => void;
    };
    // No channel yet — openPicker is a no-op.
    cmp.openPicker();
    expect(cmp.pickerOpen()).toBe(false);
    // Pick a channel — picker opens.
    cmp.form.controls.channel.setValue('email');
    cmp.openPicker();
    expect(cmp.pickerOpen()).toBe(true);
  });

  it('save creates a new trigger when no id is present', () => {
    const fixture = makeFixture();
    const cmp = fixture.componentInstance as unknown as {
      form: {
        controls: {
          name: { setValue: (v: string) => void };
          event_type: { setValue: (v: string) => void };
          channel: { setValue: (v: string) => void };
          template_id: { setValue: (v: string) => void };
        };
      };
      save: (thenTest?: boolean) => void;
    };
    cmp.form.controls.name.setValue('My trigger');
    cmp.form.controls.event_type.setValue('user.signed_up');
    cmp.form.controls.channel.setValue('email');
    cmp.form.controls.template_id.setValue('tpl-1');
    cmp.save();
    expect(apiSpy.create).toHaveBeenCalled();
    expect(apiSpy.update).not.toHaveBeenCalled();
  });

  it('runDryRun calls the api with parsed JSON payload', () => {
    const fixture = makeFixture({
      triggerId: 'trg-1',
      initialTrigger: makeTrigger(),
    });
    const cmp = fixture.componentInstance as unknown as {
      openTestModal: () => void;
      onTestPayloadInput: (v: string) => void;
      runDryRun: () => void;
      testResult: { (): unknown };
    };
    cmp.openTestModal();
    cmp.onTestPayloadInput('{"contact":{"email":"a@b.com"}}');
    cmp.runDryRun();
    expect(apiSpy.dryRun).toHaveBeenCalledWith('trg-1', {
      contact: { email: 'a@b.com' },
    });
    expect(cmp.testResult()).toBeTruthy();
  });
});
