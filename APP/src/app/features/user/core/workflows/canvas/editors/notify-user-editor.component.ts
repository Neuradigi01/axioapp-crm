import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../../shared/forms/mobile-select.component';
import { CanvasNode } from '../canvas-state.service';

const RECIPIENT_OPTIONS: ReadonlyArray<MobileSelectOption> = [
  { value: 'workflow.owner', label: 'Workflow owner' },
  { value: 'lead.owner', label: 'Lead owner' },
  { value: 'contact.assigned_to', label: "Contact's assigned rep" },
];

@Component({
  selector: 'app-notify-user-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, MobileSelectComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './notify-user-editor.component.html',
})
export class NotifyUserEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  readonly recipientOptions = RECIPIENT_OPTIONS;

  readonly recipient = computed<string>(
    () => (this.node().config?.['recipient'] as string) ?? 'workflow.owner',
  );
  readonly title = computed<string>(() => (this.node().config?.['title'] as string) ?? '');
  readonly body = computed<string>(() => (this.node().config?.['body'] as string) ?? '');

  constructor() {
    effect(() => this.validityChange.emit(this.title().trim().length > 0));
  }

  onRecipientChange(v: string): void {
    this.configChange.emit({ recipient: v });
  }
  onTitleChange(v: string): void {
    this.configChange.emit({ title: v });
  }
  onBodyChange(v: string): void {
    this.configChange.emit({ body: v });
  }
}
