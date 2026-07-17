import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  ViewChild,
  computed,
  input,
  output,
} from '@angular/core';

/**
 * Campaigns v1 Step 04 — Email HTML composer.
 *
 * v1 UX: split-pane source-vs-preview editor. The left pane is a
 * plain-text `<textarea>` bound to the parent's ``body_html`` — users
 * type HTML tags directly or paste markup exported from another tool
 * (Mailchimp, Beefree, Stripo, etc.). The right pane renders the
 * current HTML through Angular's built-in DOM sanitiser so users see
 * exactly what a mail client will render (server double-sanitises with
 * bleach on every write; the preview here is not a security boundary).
 *
 * Merge-tag inserter (top-right of the toolbar) drops the selected
 * placeholder at the caret. Kept intentionally minimal — a full
 * WYSIWYG toolbar (B/I/U + link + CTA) can layer on later without
 * changing the component contract.
 *
 * The child only owns the composer chrome; the parent form (template
 * editor OR campaign modal) owns validation and persistence.
 */

export interface MergeTagOption {
  readonly value: string;
  readonly label: string;
}

@Component({
  selector: 'app-html-composer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './html-composer.component.html',
})
export class HtmlComposerComponent {
  /** Raw HTML source. Parent binds ``[value]`` and reads
   *  ``(valueChange)``; no ControlValueAccessor plumbing on purpose so
   *  this stays a dumb component. */
  readonly value = input<string>('');

  /** Merge-tag inserter options. Default set covers contact + org
   *  fields the dispatcher resolves; parents can override to expose
   *  custom-field-driven tags. */
  readonly mergeTags = input<readonly MergeTagOption[]>([
    { value: '{{first_name}}', label: 'First name' },
    { value: '{{last_name}}', label: 'Last name' },
    { value: '{{full_name}}', label: 'Full name' },
    { value: '{{email}}', label: 'Email' },
    { value: '{{phone}}', label: 'Phone' },
  ]);

  /** Label shown above the source pane. Lets the template editor and
   *  campaign modal reuse the component with context-specific copy. */
  readonly label = input<string>('HTML body');

  /** Placeholder shown in the source textarea when empty. */
  readonly placeholder = input<string>(
    '<p>Hi {{first_name}}, this month we picked five deals for you.</p>',
  );

  /** Emits the current HTML source on every keystroke. */
  readonly valueChange = output<string>();

  /** Direct reference so we can insert text at the caret without
   *  losing the textarea's selection state. */
  @ViewChild('sourceEl') sourceEl?: ElementRef<HTMLTextAreaElement>;

  /** Character count for the toolbar. Cheap to compute — the value
   *  signal is the source of truth. */
  protected readonly charCount = computed(() => this.value().length);

  onSourceInput(event: Event): void {
    const target = event.target as HTMLTextAreaElement;
    this.valueChange.emit(target.value);
  }

  onInsertTag(token: string): void {
    const el = this.sourceEl?.nativeElement;
    if (!el) {
      // Falls back to end-of-string append when the textarea hasn't
      // rendered yet — happens on first render before any typing.
      this.valueChange.emit(this.value() + token);
      return;
    }
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    const current = el.value;
    const next = current.slice(0, start) + token + current.slice(end);
    this.valueChange.emit(next);
    // Restore caret position AFTER the inserted token so the operator
    // keeps typing where they were.
    queueMicrotask(() => {
      el.value = next;
      const caret = start + token.length;
      el.setSelectionRange(caret, caret);
      el.focus();
    });
  }
}
