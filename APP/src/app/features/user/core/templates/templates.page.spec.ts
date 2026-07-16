import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { TemplatesPageComponent } from './templates.page';
import { TemplatesApiService } from './templates-api.service';
import { FurnitureAuthService } from '../auth/auth.service';

describe('TemplatesPageComponent', () => {
  let apiSpy: jasmine.SpyObj<TemplatesApiService>;
  let authStub: { hasPermission: (k: string) => boolean };

  function makeFixture(): ComponentFixture<TemplatesPageComponent> {
    apiSpy = jasmine.createSpyObj<TemplatesApiService>('TemplatesApiService', ['list']);
    apiSpy.list.and.returnValue(of({ items: [], total: 0, limit: 25, offset: 0 }));
    authStub = { hasPermission: (_k: string) => true };

    TestBed.configureTestingModule({
      imports: [TemplatesPageComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: TemplatesApiService, useValue: apiSpy },
        { provide: FurnitureAuthService, useValue: authStub },
      ],
    });

    const fixture = TestBed.createComponent(TemplatesPageComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('renders empty state when API returns no rows', () => {
    const fixture = makeFixture();
    const text: string = fixture.nativeElement.textContent ?? '';
    expect(text).toContain('No templates yet');
  });

  it('passes the channel filter to the API on change', () => {
    const fixture = makeFixture();
    apiSpy.list.calls.reset();

    const cmp = fixture.componentInstance as unknown as {
      onChannelChange: (v: string) => void;
    };
    cmp.onChannelChange('whatsapp');
    fixture.detectChanges();

    expect(apiSpy.list).toHaveBeenCalled();
    const args = apiSpy.list.calls.mostRecent().args[0] as { channel?: string };
    expect(args.channel).toBe('whatsapp');
  });

  it('shifts offset when paginating forward', () => {
    const fixture = makeFixture();
    // Pretend the server has 50 templates so nextPage is valid.
    apiSpy.list.and.returnValue(
      of({
        items: Array.from({ length: 25 }, (_, i) => ({
          id: `id-${i}`,
          org_id: 'org',
          channel: 'email' as const,
          name: `t-${i}`,
          category: 'marketing' as const,
          language: 'en',
          body_text: 'body',
          body_html: null,
          body_text_fallback_auto: true,
          subject: 'subj',
          preview_text: null,
          variables: [],
          internal_status: 'draft' as const,
          external_status: 'n_a' as const,
          external_rejection_reason: null,
          external_provider_id: null,
          current_version: 1,
          created_by_user_id: null,
          updated_by_user_id: null,
          created_at: '2026-06-25T00:00:00Z',
          updated_at: '2026-06-25T00:00:00Z',
        })),
        total: 50,
        limit: 25,
        offset: 0,
      }),
    );
    // Trigger a reload so total becomes 50.
    const cmp = fixture.componentInstance as unknown as {
      onChannelChange: (v: string) => void;
      nextPage: () => void;
    };
    cmp.onChannelChange('');
    fixture.detectChanges();
    apiSpy.list.calls.reset();

    cmp.nextPage();
    fixture.detectChanges();

    expect(apiSpy.list).toHaveBeenCalled();
    const args = apiSpy.list.calls.mostRecent().args[0] as { offset?: number };
    expect(args.offset).toBe(25);
  });
});
