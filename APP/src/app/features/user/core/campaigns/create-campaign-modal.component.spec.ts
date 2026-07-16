import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { CreateCampaignModalComponent } from './create-campaign-modal.component';
import { CampaignsApiService } from './campaigns-api.service';
import { ContactGroupsApiService } from '../contacts/groups/groups-api.service';
import { IntegrationsApiService } from '../settings/integrations/integrations-api.service';
import { EmailAccount, EmailAccountsApiService } from '../services/email-accounts-api.service';
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
    external_rejection_reason: null,
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
  let emailAccountsSpy: jasmine.SpyObj<EmailAccountsApiService>;

  function makeFixture(
    initialTemplates: TemplateRead[] = [],
    initialEmailAccounts: EmailAccount[] = [],
  ): ComponentFixture<CreateCampaignModalComponent> {
    templatesSpy = jasmine.createSpyObj<TemplatesApiService>('TemplatesApiService', ['list']);
    templatesSpy.list.and.returnValue(
      of({
        items: initialTemplates,
        total: initialTemplates.length,
        limit: 200,
        offset: 0,
      }),
    );
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
    emailAccountsSpy = jasmine.createSpyObj<EmailAccountsApiService>('EmailAccountsApiService', [
      'listVerified',
      'list',
      'authorizeGmail',
      'authorizeMicrosoft',
      'disconnect',
    ]);
    emailAccountsSpy.listVerified.and.returnValue(of(initialEmailAccounts));

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
        { provide: EmailAccountsApiService, useValue: emailAccountsSpy },
      ],
    });

    const fixture = TestBed.createComponent(CreateCampaignModalComponent);
    fixture.detectChanges();
    return fixture;
  }

  function makeEmailAccount(overrides: Partial<EmailAccount> = {}): EmailAccount {
    return {
      id: 'acc-1',
      org_id: 'org-1',
      user_id: 'user-1',
      provider: 'gmail',
      external_account_id: 'ext-1',
      email_address: 'sales@yourshop.com',
      display_name: 'Your Shop',
      token_expires_at: null,
      scopes_granted: [],
      sync_state: 'live',
      last_sync_at: null,
      last_sync_error: null,
      daily_sent_count: 0,
      daily_sent_reset_at: '2026-07-01T00:00:00Z',
      connected_at: '2026-07-01T00:00:00Z',
      disconnected_at: null,
      disconnected_by: null,
      ...overrides,
    };
  }

  it('loads WA templates filtered by internal_status=published without an external_status filter', () => {
    // Campaigns v1 Step 01 — the WA branch used to pre-filter to
    // approved-only. Now the picker fetches every published WA
    // template (approved, pending, rejected) so the user can see
    // status inline. Non-approved rows render disabled — see the
    // "picker row disabled state" tests below.
    const fixture = makeFixture();
    void fixture;
    expect(templatesSpy.list).toHaveBeenCalled();
    const args = templatesSpy.list.calls.mostRecent().args[0];
    expect(args?.channel).toBe('whatsapp');
    expect(args?.internal_status).toBe('published');
    expect(args?.external_status).toBeUndefined();
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

  it('renders every WA template row (approved / pending / rejected) with its status badge + subtitle', () => {
    // Campaigns v1 Step 01 — three template variants must all appear
    // in the picker so the user can see status inline. Pending +
    // rejected rows exist but are visibly disabled.
    const fixture = makeFixture([
      makeTemplate({
        id: 'wa-approved',
        name: 'welcome_offer',
        body_text: 'Hi {{1}}, welcome!',
        external_status: 'approved',
      }),
      makeTemplate({
        id: 'wa-pending',
        name: 'abandoned_cart',
        category: 'transactional',
        body_text: 'Hi {{1}}, forgot something?',
        external_status: 'pending',
      }),
      makeTemplate({
        id: 'wa-rejected',
        name: 'discount_promo',
        body_text: 'FREE OFFER for {{1}}!',
        external_status: 'rejected',
      }),
    ]);
    fixture.detectChanges();

    const text: string = fixture.nativeElement.textContent ?? '';
    expect(text).toContain('welcome_offer');
    expect(text).toContain('abandoned_cart');
    expect(text).toContain('discount_promo');
    // Category + language + preview subtitle rendered for every row.
    expect(text).toContain('Marketing · en · Hi {{1}}, welcome!');
    expect(text).toContain('Transactional · en · Hi {{1}}, forgot something?');
    expect(text).toContain('Marketing · en · FREE OFFER for {{1}}!');

    // Non-approved rows are disabled at the DOM level so keyboard +
    // click both no-op cleanly.
    const buttons = fixture.nativeElement.querySelectorAll(
      'button[role="option"]',
    ) as NodeListOf<HTMLButtonElement>;
    expect(buttons.length).toBe(3);
    const [approvedBtn, pendingBtn, rejectedBtn] = Array.from(buttons);
    expect(approvedBtn.disabled).toBeFalse();
    expect(pendingBtn.disabled).toBeTrue();
    expect(rejectedBtn.disabled).toBeTrue();
  });

  it('selects an approved WA row on click; pending/rejected rows are a no-op', () => {
    const fixture = makeFixture([
      makeTemplate({ id: 'wa-approved', external_status: 'approved' }),
      makeTemplate({ id: 'wa-pending', external_status: 'pending' }),
      makeTemplate({ id: 'wa-rejected', external_status: 'rejected' }),
    ]);
    fixture.detectChanges();
    const cmp = fixture.componentInstance as unknown as {
      selectedTemplateId: () => string | null;
    };

    const buttons = fixture.nativeElement.querySelectorAll(
      'button[role="option"]',
    ) as NodeListOf<HTMLButtonElement>;
    const [approvedBtn, pendingBtn, rejectedBtn] = Array.from(buttons);

    approvedBtn.click();
    fixture.detectChanges();
    expect(cmp.selectedTemplateId()).toBe('wa-approved');

    // Programmatic click on a disabled button doesn't fire the handler
    // — but even if the operator managed to trigger it (e.g. via a
    // custom accessibility path), the guard in `onRowClick` still
    // leaves the selection unchanged.
    pendingBtn.click();
    fixture.detectChanges();
    expect(cmp.selectedTemplateId()).toBe('wa-approved');

    rejectedBtn.click();
    fixture.detectChanges();
    expect(cmp.selectedTemplateId()).toBe('wa-approved');
  });

  it('non-WhatsApp channels render rows without the status badge and every row is selectable', () => {
    const fixture = makeFixture();
    // Prime the spy with an email template ready for the channel switch.
    templatesSpy.list.and.returnValue(
      of({
        items: [
          makeTemplate({
            id: 'em-1',
            channel: 'email',
            name: 'monthly_newsletter',
            body_text: 'Hi {{contact.first_name}}, this month…',
            external_status: 'n_a',
            subject: 'July deals',
          }),
        ],
        total: 1,
        limit: 200,
        offset: 0,
      }),
    );
    const cmp = fixture.componentInstance as unknown as {
      form: { controls: { channel: { setValue: (v: string) => void } } };
    };
    cmp.form.controls.channel.setValue('email');
    fixture.detectChanges();

    // No badge is rendered for non-WA channels — the badge label from
    // TemplateStatusBadgeComponent (e.g. "Provider approved") never
    // appears in the picker text.
    const text: string = fixture.nativeElement.textContent ?? '';
    expect(text).toContain('monthly_newsletter');
    expect(text).toContain('Marketing · en · Hi {{contact.first_name}}, this month…');
    expect(text).not.toContain('Provider approved');
    expect(text).not.toContain('Provider rejected');
    expect(text).not.toContain('Pending review');

    const buttons = fixture.nativeElement.querySelectorAll(
      'button[role="option"]',
    ) as NodeListOf<HTMLButtonElement>;
    expect(buttons.length).toBe(1);
    expect(buttons[0].disabled).toBeFalse();
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

  // --- Campaigns v1 Step 03 — Email sender identity + subject + preheader ---

  it('renders the Email sender identity fieldset only when channel = email', () => {
    const fixture = makeFixture([], [makeEmailAccount()]);
    const cmp = fixture.componentInstance as unknown as {
      form: { controls: { channel: { setValue: (v: string) => void } } };
    };

    // WhatsApp default — the Email fieldset stays hidden.
    let text: string = fixture.nativeElement.textContent ?? '';
    expect(text).not.toContain('Email sender identity');

    cmp.form.controls.channel.setValue('email');
    fixture.detectChanges();
    text = fixture.nativeElement.textContent ?? '';
    expect(text).toContain('Email sender identity');
    expect(text).toContain('Send from mailbox');
    expect(text).toContain('Sender name');
    expect(text).toContain('Reply-to (optional)');
    expect(text).toContain('Subject');
    expect(text).toContain('Preheader (optional)');

    // Switching back to WhatsApp hides the Email block again.
    cmp.form.controls.channel.setValue('whatsapp');
    fixture.detectChanges();
    text = fixture.nativeElement.textContent ?? '';
    expect(text).not.toContain('Email sender identity');
  });

  it('shows the empty-state banner when the org has no verified mailboxes', () => {
    const fixture = makeFixture([], []);
    const cmp = fixture.componentInstance as unknown as {
      form: { controls: { channel: { setValue: (v: string) => void } } };
    };
    cmp.form.controls.channel.setValue('email');
    fixture.detectChanges();

    const text: string = fixture.nativeElement.textContent ?? '';
    expect(text).toContain('No verified sender mailbox');
    expect(text).toContain('Settings → Email');
  });

  it('lazy-fetches verified mailboxes only when the operator picks Email', () => {
    const fixture = makeFixture([], [makeEmailAccount()]);
    // Default channel is whatsapp — no fetch yet.
    expect(emailAccountsSpy.listVerified).not.toHaveBeenCalled();

    const cmp = fixture.componentInstance as unknown as {
      form: { controls: { channel: { setValue: (v: string) => void } } };
    };
    cmp.form.controls.channel.setValue('email');
    fixture.detectChanges();
    expect(emailAccountsSpy.listVerified).toHaveBeenCalledTimes(1);

    // Switching back and forth doesn't refetch — the accounts signal
    // is cached for the lifetime of the modal.
    cmp.form.controls.channel.setValue('whatsapp');
    cmp.form.controls.channel.setValue('email');
    fixture.detectChanges();
    expect(emailAccountsSpy.listVerified).toHaveBeenCalledTimes(1);
  });

  it('disables the submit button until every required Email field is filled', () => {
    const fixture = makeFixture([], [makeEmailAccount()]);
    const cmp = fixture.componentInstance as unknown as {
      form: {
        controls: {
          channel: { setValue: (v: string) => void };
          name: { setValue: (v: string) => void };
          email_account_id: { setValue: (v: string | null) => void };
          sender_name: { setValue: (v: string | null) => void };
          subject: { setValue: (v: string | null) => void };
        };
      };
      emailBranchIncomplete: () => boolean;
    };
    cmp.form.controls.channel.setValue('email');
    cmp.form.controls.name.setValue('July newsletter');
    fixture.detectChanges();
    expect(cmp.emailBranchIncomplete()).toBeTrue();

    cmp.form.controls.email_account_id.setValue('acc-1');
    fixture.detectChanges();
    expect(cmp.emailBranchIncomplete()).toBeTrue();

    cmp.form.controls.sender_name.setValue('Your Shop');
    fixture.detectChanges();
    expect(cmp.emailBranchIncomplete()).toBeTrue();

    cmp.form.controls.subject.setValue('July deals');
    fixture.detectChanges();
    expect(cmp.emailBranchIncomplete()).toBeFalse();
  });

  it('appends merge tags to the subject via onInsertSubjectTag', () => {
    const fixture = makeFixture([], [makeEmailAccount()]);
    const cmp = fixture.componentInstance as unknown as {
      form: {
        controls: {
          channel: { setValue: (v: string) => void };
          subject: { setValue: (v: string | null) => void; value: string | null };
        };
      };
      onInsertSubjectTag: (t: string) => void;
    };
    cmp.form.controls.channel.setValue('email');
    fixture.detectChanges();
    cmp.form.controls.subject.setValue('July deals for ');
    cmp.onInsertSubjectTag('{{first_name}}');
    expect(cmp.form.controls.subject.value).toBe('July deals for {{first_name}}');
  });

  it('clears the Email fields when switching back to WhatsApp', () => {
    const fixture = makeFixture([], [makeEmailAccount()]);
    const cmp = fixture.componentInstance as unknown as {
      form: {
        controls: {
          channel: { setValue: (v: string) => void };
          email_account_id: { setValue: (v: string | null) => void; value: string | null };
          sender_name: { setValue: (v: string | null) => void; value: string | null };
          subject: { setValue: (v: string | null) => void; value: string | null };
          preheader: { setValue: (v: string | null) => void; value: string | null };
        };
      };
    };
    cmp.form.controls.channel.setValue('email');
    cmp.form.controls.email_account_id.setValue('acc-1');
    cmp.form.controls.sender_name.setValue('Your Shop');
    cmp.form.controls.subject.setValue('July deals');
    cmp.form.controls.preheader.setValue('This month picks');

    cmp.form.controls.channel.setValue('whatsapp');
    fixture.detectChanges();

    expect(cmp.form.controls.email_account_id.value).toBeNull();
    expect(cmp.form.controls.sender_name.value).toBeNull();
    expect(cmp.form.controls.subject.value).toBeNull();
    expect(cmp.form.controls.preheader.value).toBeNull();
  });
});
