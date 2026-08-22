/**
 * Settings → Integrations → Retention configuration card
 * (``tasks/ai-assistants`` Step 17).
 *
 * Small read-only card displaying org-level default retention-days setting
 * for AI conversations. Individual assistants can override this at edit time.
 *
 * Standalone component with ChangeDetectionStrategy.OnPush.
 */

import { ChangeDetectionStrategy, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';

@Component({
  selector: 'app-retention-card',
  standalone: true,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './retention-card.component.html',
  styleUrls: [],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RetentionCardComponent {
  protected readonly defaultRetentionDays = 90;
}
