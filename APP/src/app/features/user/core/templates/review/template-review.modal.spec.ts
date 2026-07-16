import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { TemplateReviewModalComponent } from './template-review.modal';
import { TemplateRead, TemplatesApiService } from '../templates-api.service';

function makeTemplate(): TemplateRead {
  return {
    id: 'template-1',
    org_id: 'org-1',
    channel: 'email',
    name: 'Welcome',
    category: 'transactional',
    language: 'en',
    body_text: 'Hi',
    subject: 'Welcome',
    preview_text: null,
    variables: [],
    internal_status: 'in_review',
    external_status: 'n_a',
    external_rejection_reason: null,
    external_provider_id: null,
    current_version: 1,
    created_by_user_id: null,
    updated_by_user_id: null,
    created_at: '2026-06-25T00:00:00Z',
    updated_at: '2026-06-25T00:00:00Z',
  };
}

describe('TemplateReviewModalComponent', () => {
  let apiSpy: jasmine.SpyObj<TemplatesApiService>;

  function makeFixture(): ComponentFixture<TemplateReviewModalComponent> {
    apiSpy = jasmine.createSpyObj<TemplatesApiService>('TemplatesApiService', [
      'approve',
      'reject',
      'requestChanges',
    ]);
    apiSpy.approve.and.returnValue(of(makeTemplate()));
    apiSpy.reject.and.returnValue(of(makeTemplate()));
    apiSpy.requestChanges.and.returnValue(of(makeTemplate()));

    TestBed.configureTestingModule({
      imports: [TemplateReviewModalComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: TemplatesApiService, useValue: apiSpy },
      ],
    });

    const fixture = TestBed.createComponent(TemplateReviewModalComponent);
    fixture.componentRef.setInput('template', makeTemplate());
    fixture.detectChanges();
    return fixture;
  }

  it('blocks submit when action is reject and note is empty', () => {
    const fixture = makeFixture();
    const cmp = fixture.componentInstance as unknown as {
      setAction: (a: 'approve' | 'request_changes' | 'reject') => void;
      canSubmit: () => boolean;
      onNoteInput: (v: string) => void;
    };

    cmp.setAction('reject');
    fixture.detectChanges();
    expect(cmp.canSubmit()).toBe(false);

    cmp.onNoteInput('Needs more detail');
    fixture.detectChanges();
    expect(cmp.canSubmit()).toBe(true);
  });

  it('approve route accepts an empty note', () => {
    const fixture = makeFixture();
    const cmp = fixture.componentInstance as unknown as {
      setAction: (a: 'approve') => void;
      canSubmit: () => boolean;
    };
    cmp.setAction('approve');
    fixture.detectChanges();
    expect(cmp.canSubmit()).toBe(true);
  });

  it('submit() calls the matching API method', () => {
    const fixture = makeFixture();
    const cmp = fixture.componentInstance as unknown as {
      setAction: (a: 'approve' | 'reject') => void;
      onNoteInput: (v: string) => void;
      submit: () => void;
    };

    cmp.setAction('reject');
    cmp.onNoteInput('No.');
    fixture.detectChanges();
    cmp.submit();
    expect(apiSpy.reject).toHaveBeenCalledTimes(1);
    expect(apiSpy.approve).not.toHaveBeenCalled();
  });

  it('shows the error message when the API rejects', () => {
    const fixture = makeFixture();
    apiSpy.approve.and.returnValue(throwError(() => ({ error: { detail: 'workflow refused' } })));
    const cmp = fixture.componentInstance as unknown as {
      setAction: (a: 'approve') => void;
      submit: () => void;
      error: () => string | null;
    };
    cmp.setAction('approve');
    cmp.submit();
    fixture.detectChanges();
    expect(cmp.error()).toContain('workflow refused');
  });
});
