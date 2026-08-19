/**
 * Styling tab — placeholder shell
 * (``tasks/ai-assistants`` Step 7). Step 13 fills in: theme mode,
 * assistant shape, 8 colour tokens, header profile picture upload.
 */
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

@Component({
  selector: 'app-ai-assistant-styling-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './styling-tab.component.html',
})
export class StylingTabComponent {}
