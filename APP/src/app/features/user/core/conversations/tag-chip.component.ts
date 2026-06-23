import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import {
  ConversationTagRef,
  TAG_COLOR_CLASSES,
  TagColor,
} from './conversations-api.service';

/**
 * Tag chip (whatsapp-platform-upgrade Step 14).
 *
 * Tiny shared component used in three places:
 *   - inline list rows (compact, max 3 visible + "+N more")
 *   - conversation header (full chip row)
 *   - tag-manager dropdown (with remove × on the active conversation)
 *
 * `removable=true` shows an X button that emits `(remove)`.
 */
@Component({
  selector: 'app-tag-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    <span
      [class]="
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ' +
        colorClasses()
      "
    >
      <span class="truncate max-w-[120px]">{{ tag.name }}</span>
      @if (removable) {
        <button
          type="button"
          (click)="$event.stopPropagation(); remove.emit(tag.id)"
          class="rounded-full hover:bg-black/10"
          aria-label="Remove tag"
        >
          <lucide-icon name="x" size="10" />
        </button>
      }
    </span>
  `,
})
export class TagChipComponent {
  @Input({ required: true }) tag!: ConversationTagRef;
  @Input() removable = false;

  @Output() readonly remove = new EventEmitter<string>();

  protected colorClasses(): string {
    return (
      TAG_COLOR_CLASSES[this.tag.color as TagColor] ??
      TAG_COLOR_CLASSES.zinc
    );
  }
}
