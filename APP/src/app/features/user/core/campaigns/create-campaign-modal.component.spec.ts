import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { CreateCampaignModalComponent } from './create-campaign-modal.component';
import { CampaignsApiService } from './campaigns-api.service';
import { ContactGroupsApiService } from '../contacts/groups/groups-api.service';
import { IntegrationsApiService } from '../settings/integrations/integrations-api.service';
import { TemplateRead, TemplatesApiService } from '../templates/templates-api.service';

/**
 * Step 15 — verifies the campaign Create modal's picker reads from
 * the central template library (not the legacy WA integrations
 * endpoint), filters channel-aware, and resets cleanly on channel
 * change.
 */

function makeTemplate(overrides: Partial<TemplateRead> = {}): TemplateRead {
  return {
    id: 'tpl-1',
    org_id: 'org-1',
    channel: 'whatsapp',
    name: 'WA Welcome',
    category: 'marketing',
    language: 'en',
    body_text: 'Hi {{1}}',
    subject: null,
    preview_text: null,
    variables: [],
    internal_status: 'published',
    external_status: 'approved',
    external_provider_id: null,
    current_version: 1,
    created_by_user_id: null,
    updated_by_user_id: null,
    created_at: '2026-06-25T00:00:00Z',
    updated_at: '2026-06-25T00:00:00Z',
    ...overrides,
  };
}

describe('CreateCampaignModalComponent — Step 15 picker swap', () => {
  let templatesSpy: jasmine.SpyObj<TemplatesApiService>;
  let integrationsSpy: jasmine.SpyObj<IntegrationsApiService>;
  let campaignsSpy: jasmine.SpyObj<CampaignsApiService>;
  let groupsSpy: jasmine.SpyObj<ContactGroupsApiService>;

  function makeFixture(): ComponentFixture<CreateCampaignModalComponent> {
    templatesSpy = jasmine.createSpyObj<TemplatesApiService>('TemplatesApiService', ['list']);
    templatesSpy.list.and.returnValue(of({ items: [], total: 0, limit: 200, offset: 0 }));
    integrationsSpy = jasmine.createSpyObj<IntegrationsApiService>('IntegrationsApiService', [
      'getWhatsAppCapacity',
      'listWhatsAppTemplates',
    ]);
    integrationsSpy.getWhatsAppCapacity.and.returnValue(
      of({
        is_unlimited: true,
        usage_percent: 0,
        sent_today: 0,
        remaining: 1000,
        daily_limit: 1000,
      } as never),
    );
    integrationsSpy.listWhatsAppTemplates.and.returnValue(of([]));
    campaignsSpy = jasmine.createSpyObj<CampaignsApiService>('CampaignsApiService', ['create']);
    groupsSpy = jasmine.createSpyObj<ContactGroupsApiService>('ContactGroupsApiService', [
      'list',
      'previewSize',
    ]);
    groupsSpy.list.and.returnValue(of({ items: [], total: 0, page: 1, size: 0 }));
    groupsSpy.previewSize.and.returnValue(of({ count: 0 }));

    TestBed.configureTestingModule({
      imports: [CreateCampaignModalComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: TemplatesApiService, useValue: templatesSpy },
        { provide: IntegrationsApiService, useValue: integrationsSpy },
        { provide: CampaignsApiService, useValue: campaignsSpy },
        { provide: ContactGroupsApiService, useValue: groupsSpy },
      ],
    });

    const fixture = TestBed.createComponent(CreateCampaignModalComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('loads WA templates filtered by internal_status=published AND external_status=approved', () => {
    const fixture = makeFixture();
    void fixture;
    // Initial load fires for the default channel (whatsapp).
    expect(templatesSpy.list).toHaveBeenCalled();
    const args = templatesSpy.list.calls.mostRecent().args[0];
    expect(args?.channel).toBe('whatsapp');
    expect(args?.internal_status).toBe('published');
    expect(args?.external_status).toBe('approved');
  });

  it('loads non-WA templates filtered by internal_status=published only', () => {
    const fixture = makeFixture();
    templatesSpy.list.calls.reset();

    // Switch channel to email — the picker should re-fire, this time
    // WITHOUT the external_status filter (no external review for email).
    const cmp = fixture.componentInstance as unknown as {
      form: { controls: { channel: { setValue: (v: string) => void } } };
    };
    cmp.form.controls.channel.setValue('email');
    fixture.detectChanges();

    expect(templatesSpy.list).toHaveBeenCalled();
    const args = templatesSpy.list.calls.mostRecent().args[0];
    expect(args?.channel).toBe('email');
    expect(args?.internal_status).toBe('published');
    expect(args?.external_status).toBeUndefined();
  });

  it('resets selectedTemplateId when channel changes', () => {
    const fixture = makeFixture();
    const cmp = fixture.componentInstance as unknown as {
      selectedTemplateId: { set: (v: string | null) => void; (): string | null };
      form: { controls: { channel: { setValue: (v: string) => void } } };
    };
    cmp.selectedTemplateId.set('tpl-1');
    expect(cmp.selectedTemplateId()).toBe('tpl-1');

    cmp.form.controls.channel.setValue('email');
    fixture.detectChanges();
    expect(cmp.selectedTemplateId()).toBeNull();
  });

  it('hides the positional variable panel for non-WA templates', () => {
    const fixture = makeFixture();
    // Make the list call resolve with one named-variable email
    // template (no `{{n}}` positional placeholders).
    templatesSpy.list.and.returnValue(
      of({
        items: [
          makeTemplate({
            id: 'tpl-email-1',
            channel: 'email',
            body_text: 'Hi {{contact.first_name}}',
            external_status: 'n_a',
          }),
        ],
        total: 1,
        limit: 200,
        offset: 0,
      }),
    );
    const cmp = fixture.componentInstance as unknown as {
      form: { controls: { channel: { setValue: (v: string) => void } } };
      selectedTemplateId: { set: (v: string | null) => void };
      templateVariableNumbers: () => number[];
    };
    cmp.form.controls.channel.setValue('email');
    fixture.detectChanges();
    cmp.selectedTemplateId.set('tpl-email-1');
    fixture.detectChanges();

    expect(cmp.templateVariableNumbers()).toEqual([]);
    const text: string = fixture.nativeElement.textContent ?? '';
    expect(text).not.toContain('Variable bindings');
    expect(text).toContain('Variables resolve from each contact');
  });
});
