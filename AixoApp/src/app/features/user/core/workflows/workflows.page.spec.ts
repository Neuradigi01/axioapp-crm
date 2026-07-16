import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { WorkflowsPageComponent } from './workflows.page';
import { WorkflowRead, WorkflowStatus, WorkflowsApiService } from './workflows-api.service';
import { FurnitureAuthService } from '../auth/auth.service';

function makeWorkflow(overrides: Partial<WorkflowRead> = {}): WorkflowRead {
  return {
    id: 'wf-1',
    org_id: 'org-1',
    name: 'Welcome series',
    description: null,
    category: 'Marketing',
    folder_id: null,
    status: 'draft',
    current_version: 1,
    re_enrollment_rule: 'once',
    is_marketing: true,
    graph: { nodes: [], edges: [] },
    goal_node_id: null,
    cost_per_run_cents: 0,
    enabled_event_types: ['email.opened'],
    ab_sibling_id: null,
    created_at: '2026-06-29T00:00:00Z',
    updated_at: '2026-06-29T00:00:00Z',
    ...overrides,
  };
}

describe('WorkflowsPageComponent', () => {
  let apiSpy: jasmine.SpyObj<WorkflowsApiService>;
  let authStub: { hasPermission: (k: string) => boolean };
  let permissions: string[];

  function makeFixture(initialRows: WorkflowRead[] = []): ComponentFixture<WorkflowsPageComponent> {
    apiSpy = jasmine.createSpyObj<WorkflowsApiService>('WorkflowsApiService', [
      'list',
      'listFolders',
      'activate',
      'pause',
      'archive',
      'clone',
      'createFolder',
      'patchFolder',
      'deleteFolder',
      'listRuns',
      'listRunSteps',
    ]);
    apiSpy.list.and.returnValue(of({ items: initialRows, total: initialRows.length }));
    apiSpy.listFolders.and.returnValue(of([]));

    authStub = { hasPermission: (k: string) => permissions.includes(k) };

    TestBed.configureTestingModule({
      imports: [WorkflowsPageComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: WorkflowsApiService, useValue: apiSpy },
        { provide: FurnitureAuthService, useValue: authStub },
      ],
    });

    const fixture = TestBed.createComponent(WorkflowsPageComponent);
    fixture.detectChanges();
    return fixture;
  }

  beforeEach(() => {
    permissions = ['workflows.read', 'workflows.write', 'workflows.activate', 'workflows.clone'];
  });

  it('renders the empty state when the API returns no rows', () => {
    const fixture = makeFixture();
    const text: string = fixture.nativeElement.textContent ?? '';
    expect(text).toContain('No workflows yet');
    expect(text).toContain('Start from template');
  });

  it('channel filter narrows visible rows to that prefix', () => {
    const fixture = makeFixture([
      makeWorkflow({ id: 'wf-1', enabled_event_types: ['email.opened'] }),
      makeWorkflow({ id: 'wf-2', enabled_event_types: ['whatsapp.replied'] }),
    ]);

    const cmp = fixture.componentInstance as unknown as {
      onChannelChange: (v: string) => void;
      items: () => WorkflowRead[];
    };
    cmp.onChannelChange('whatsapp');
    fixture.detectChanges();

    const ids = cmp.items().map((r) => r.id);
    expect(ids).toEqual(['wf-2']);
  });

  it('status filter is passed through to the api.list call', () => {
    const fixture = makeFixture();
    apiSpy.list.calls.reset();

    const cmp = fixture.componentInstance as unknown as {
      onStatusChange: (v: WorkflowStatus | '') => void;
    };
    cmp.onStatusChange('active');
    fixture.detectChanges();

    expect(apiSpy.list).toHaveBeenCalled();
    const args = apiSpy.list.calls.mostRecent().args[0];
    expect(args?.status).toBe('active');
  });

  it('hides the "New workflow" CTA when the user lacks workflows.write', () => {
    permissions = ['workflows.read'];
    const fixture = makeFixture();
    const text: string = fixture.nativeElement.textContent ?? '';
    expect(text).not.toContain('New workflow');
  });
});
