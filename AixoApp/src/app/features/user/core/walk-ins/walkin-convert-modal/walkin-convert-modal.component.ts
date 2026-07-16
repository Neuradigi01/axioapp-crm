import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
} from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { WalkIn } from '../walk-ins-api.service';

/**
 * Payload emitted on confirm — flows straight into the API service's
 * `convert()` body. Walk-in → Lead conversion is light: in v1 the
 * contact-link-mode is fixed to `auto` (keep the walk-in's existing
 * contact) and only an optional note flows through. The radio for
 * Create-new-contact / Link-existing-contact is a v2 polish that
 * needs a contact picker; keep this modal minimal for now.
 */
export interface ConvertConfirm {
  contact_link_mode: 'auto' | 'link';
  linked_contact_id: string | null;
  notes: string | null;
}

@Component({
  selector: 'app-walkin-convert-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './walkin-convert-modal.component.html',
})
export class WalkinConvertModalComponent {
  protected readonly _walkIn = signal<WalkIn | null>(null);
  protected readonly _submitting = signal(false);
  protected readonly _error = signal<string | null>(null);

  @Input() set walkIn(value: WalkIn | null) {
    this._walkIn.set(value);
  }

  @Input() set submitting(v: boolean) {
    this._submitting.set(v);
  }

  @Input() set error(v: string | null) {
    this._error.set(v);
  }

  @Output() readonly confirm = new EventEmitter<ConvertConfirm>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly notesControl = new FormControl<string>('', {
    nonNullable: true,
  });

  protected onConfirm(): void {
    if (this._submitting()) return;
    const notes = this.notesControl.value.trim();
    this.confirm.emit({
      contact_link_mode: 'auto',
      linked_contact_id: null,
      notes: notes || null,
    });
  }
}
