/**
 * Knowledge Source tab — placeholder shell
 * (``tasks/ai-assistants`` Step 7). Step 11 fills in: three-mode
 * segment (file / custom text / URL), sources list with progress +
 * cancel, replace-in-place flow.
 */
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

@Component({
  selector: 'app-ai-assistant-knowledge-source-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './knowledge-source-tab.component.html',
})
export class KnowledgeSourceTabComponent {}
