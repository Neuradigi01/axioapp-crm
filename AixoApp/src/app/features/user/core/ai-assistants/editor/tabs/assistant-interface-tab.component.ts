/**
 * Assistant Interface tab — placeholder shell
 * (``tasks/ai-assistants`` Step 7). Step 12 fills in: header +
 * subheader, initial-message chips (max 2), Powered-By toggle,
 * footer text + link.
 */
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

@Component({
  selector: 'app-ai-assistant-interface-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './assistant-interface-tab.component.html',
})
export class AssistantInterfaceTabComponent {}
