/**
 * Reusable colour swatch + hex input
 * (``tasks/ai-assistants`` Step 13).
 *
 * Two-way-ish input:
 *   * ``value`` binds the current hex string (e.g. ``"#128C7E"``).
 *   * Native ``<input type="color">`` shows the OS colour picker.
 *   * Text input lets the operator paste a hex directly.
 *
 * Emits ``valueChange`` only when the string parses as a valid hex
 * literal (``#RGB`` / ``#RRGGBB`` / ``#RRGGBBAA``). Invalid strokes
 * keep the local draft but leave the parent's bound value untouched
 * until the operator commits a valid value — no partial "#12" ever
 * leaks into ``styling_config``.
 */
import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  signal,
} from '@angular/core';

const HEX_RE = /^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i;

@Component({
  selector: 'app-color-input',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  templateUrl: './color-input.component.html',
})
export class ColorInputComponent {
  /** Committed value from the parent form-state. Kept as a signal
   *  so the template + swatch update when the parent hydrates. */
  private readonly _value = signal<string>('#000000');
  @Input({ required: true }) set value(v: string) {
    this._value.set(v);
    // Reset the local draft so a re-hydrate (e.g. Save round-trip)
    // drops any invalid in-progress edit.
    this.draft.set(v);
  }
  get value(): string {
    return this._value();
  }

  @Input() label = '';
  @Input() helpText: string | null = null;
  @Input() id = '';

  @Output() readonly valueChange = new EventEmitter<string>();

  /** Local text-input draft — mirrors the committed value until the
   *  operator types something invalid, in which case it diverges
   *  visually so they see the bad hex without silently corrupting
   *  the form-state. */
  protected readonly draft = signal<string>('#000000');

  /** True when the current draft is a syntactically valid hex. Used
   *  to red-outline the text input on invalid input. */
  protected readonly draftValid = computed(() => HEX_RE.test(this.draft()));

  /** The colour the native picker + swatch render — always the
   *  committed value (never the invalid draft) so the swatch stays
   *  useful during editing. */
  protected readonly swatchColor = computed(() => this._value());

  protected onSwatchInput(event: Event): void {
    // Native colour picker always yields ``#RRGGBB`` — safe to commit
    // without a regex round-trip.
    const raw = (event.target as HTMLInputElement).value;
    this.draft.set(raw);
    this._value.set(raw);
    this.valueChange.emit(raw);
  }

  protected onTextInput(event: Event): void {
    const raw = (event.target as HTMLInputElement).value.trim();
    this.draft.set(raw);
    if (HEX_RE.test(raw)) {
      // Normalise so the parent always stores an upper-case hex —
      // downstream comparisons don't care but consistency helps
      // when the operator eyeballs the JSONB.
      const normalised = raw.toUpperCase();
      this._value.set(normalised);
      this.valueChange.emit(normalised);
    }
  }
}
