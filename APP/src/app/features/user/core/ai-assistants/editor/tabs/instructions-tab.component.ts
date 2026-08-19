/**
 * AI Instructions tab — placeholder shell
 * (``tasks/ai-assistants`` Step 7). Step 8 fills in: instruction-type
 * dropdown, prompt textarea, temperature slider, provider-key +
 * model selects, stop-keyword chips, retry/fallback controls,
 * allowed_domains list, budget cap override.
 */
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

@Component({
  selector: 'app-ai-assistant-instructions-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './instructions-tab.component.html',
})
export class InstructionsTabComponent {}
