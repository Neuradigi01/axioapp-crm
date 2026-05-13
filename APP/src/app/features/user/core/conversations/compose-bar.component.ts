import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

/**
 * Compose bar — input + send + "Let AI handle it" toggle. Enter
 * submits, Shift+Enter inserts a newline. The AI toggle writes the
 * `ai_handling` flag via the parent's `toggleAi` output.
 */
@Component({
  selector: 'app-compose-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, LucideAngularModule],
  templateUrl: './compose-bar.component.html',
})
export class ComposeBarComponent {
  @Input() aiHandling = false;

  @Output() readonly send = new EventEmitter<string>();
  @Output() readonly toggleAi = new EventEmitter<boolean>();

  protected readonly text = signal<string>('');

  protected onTextChange(value: string): void {
    this.text.set(value);
  }

  protected submit(): void {
    const v = this.text().trim();
    if (!v) return;
    this.send.emit(v);
    this.text.set('');
  }

  protected onKey(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.submit();
    }
  }

  protected flipAi(): void {
    this.toggleAi.emit(!this.aiHandling);
  }
}
