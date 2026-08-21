/**
 * Knowledge Source tab (``tasks/ai-assistants`` Step 11).
 *
 * Three-segment control at the top (file / custom text / URL) selects
 * which input panel is visible; the sources list renders below and
 * receives change events from every panel so a freshly-created row
 * shows up without a round-trip.
 *
 * Each sub-component is small + focused so a future skin change
 * (segment style, drop-zone layout, list density) hits one file.
 * The panels don't talk to each other — the tab shell is the single
 * "row appended → refresh list" pivot.
 */
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { AssistantFormStateService } from '../../form-state.service';
import { CustomDataPanelComponent } from './knowledge/custom-data-panel.component';
import { SourcesListComponent } from './knowledge/sources-list.component';
import { UploadFilePanelComponent } from './knowledge/upload-file-panel.component';
import { UrlPanelComponent } from './knowledge/url-panel.component';

type PanelId = 'file' | 'text' | 'url';

interface PanelDescriptor {
  id: PanelId;
  label: string;
  icon: string;
  // Rendered as a disabled "Coming Soon" pill on the segmented
  // control — the backend endpoint stays wired (SSRF-safe fetch +
  // Celery ingest ship today) but the UI is gated until HTML
  // extraction handles JS-rendered SPAs and anti-bot pages
  // reliably enough for customer knowledge bases.
  comingSoon?: boolean;
}

const PANELS: readonly PanelDescriptor[] = [
  { id: 'file', label: 'Upload File', icon: 'upload-cloud' },
  { id: 'text', label: 'Custom Data', icon: 'file-text' },
  { id: 'url', label: 'URL', icon: 'link', comingSoon: true },
];

@Component({
  selector: 'app-ai-assistant-knowledge-source-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    LucideAngularModule,
    UploadFilePanelComponent,
    CustomDataPanelComponent,
    UrlPanelComponent,
    SourcesListComponent,
  ],
  templateUrl: './knowledge-source-tab.component.html',
})
export class KnowledgeSourceTabComponent {
  protected readonly formState = inject(AssistantFormStateService);

  protected readonly panels = PANELS;
  protected readonly activePanel = signal<PanelId>('file');

  /** Bumped whenever a panel creates a new source. Sources-list
   *  subscribes to this signal via its ``refreshTick`` input +
   *  re-issues its ``GET /knowledge`` request. Cheaper than
   *  wiring an EventEmitter chain up + down for a tiny event. */
  protected readonly listRefreshTick = signal(0);

  protected setPanel(id: PanelId): void {
    const panel = this.panels.find((p) => p.id === id);
    if (panel?.comingSoon) return;
    this.activePanel.set(id);
  }

  protected onCreated(): void {
    this.listRefreshTick.update((n) => n + 1);
  }
}
