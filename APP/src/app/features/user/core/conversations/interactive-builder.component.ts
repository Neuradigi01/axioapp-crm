/**
 * Interactive-message builder modal (whatsapp-platform-upgrade Step 6).
 *
 * Three modes — Reply buttons, CTA URL, List — each with its own form
 * + live preview pane. The operator opens this from the compose bar's
 * `+` trigger; on submit the dialog emits the structured payload the
 * conversations API expects on `POST /messages` (the `interactive`
 * discriminated union mirrors the backend's Pydantic schema).
 *
 * Validation matches Meta's published limits exactly so a bad build
 * never reaches the Cloud API. Tightening / loosening here without
 * matching the backend will produce confusing 422s — keep the two
 * sides in sync.
 */
import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
  computed,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

export type InteractiveKind = 'reply_buttons' | 'cta_url' | 'list';

export interface ReplyButtonsPayload {
  kind: 'reply_buttons';
  body: string;
  buttons: Array<{ id: string; title: string }>;
  header?: { text: string };
  footer?: string;
}

export interface CtaUrlPayload {
  kind: 'cta_url';
  body: string;
  button_text: string;
  url: string;
  header?: { text: string };
  footer?: string;
}

export interface ListPayload {
  kind: 'list';
  body: string;
  button_text: string;
  sections: Array<{
    title: string;
    rows: Array<{ id: string; title: string; description?: string }>;
  }>;
  header?: { text: string };
  footer?: string;
}

export type InteractivePayload = ReplyButtonsPayload | CtaUrlPayload | ListPayload;

// Mirror of backend caps in `core/conversations/schemas.py`. Keep in
// lockstep — see module docstring.
const LIMITS = {
  headerMax: 60,
  bodyMax: 1024,
  footerMax: 60,
  buttonTitleMax: 20,
  buttonIdMax: 256,
  buttonsMax: 3,
  ctaUrlMax: 2000,
  listButtonMax: 20,
  listSectionTitleMax: 24,
  listRowTitleMax: 24,
  listRowDescriptionMax: 72,
  listRowIdMax: 200,
  listRowsMax: 10,
  listSectionsMax: 10,
} as const;

interface ReplyButtonForm {
  id: string;
  title: string;
}

interface ListRowForm {
  id: string;
  title: string;
  description: string;
}

interface ListSectionForm {
  title: string;
  rows: ListRowForm[];
}

@Component({
  selector: 'app-interactive-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  templateUrl: './interactive-builder.component.html',
})
export class InteractiveBuilderComponent {
  @Input() open = false;

  @Output() readonly cancel = new EventEmitter<void>();
  @Output() readonly submit = new EventEmitter<InteractivePayload>();

  protected readonly LIMITS = LIMITS;

  protected readonly kind = signal<InteractiveKind>('reply_buttons');

  protected readonly body = signal('');
  protected readonly headerText = signal('');
  protected readonly footerText = signal('');

  // Reply buttons mode.
  protected readonly buttons = signal<ReplyButtonForm[]>([
    { id: 'btn_1', title: '' },
    { id: 'btn_2', title: '' },
  ]);

  // CTA URL mode.
  protected readonly ctaButtonText = signal('');
  protected readonly ctaUrl = signal('');

  // List mode.
  protected readonly listButtonText = signal('Choose');
  protected readonly sections = signal<ListSectionForm[]>([
    {
      title: '',
      rows: [
        { id: 'row_1', title: '', description: '' },
        { id: 'row_2', title: '', description: '' },
      ],
    },
  ]);

  // Surfaced inline above the submit button so the operator sees the
  // first failing rule on a malformed build rather than a generic
  // "disabled" state.
  protected readonly validationError = computed(() => this.validate());

  protected readonly canSubmit = computed(() => this.validationError() === null);

  protected readonly totalListRows = computed(() =>
    this.sections().reduce((acc, s) => acc + s.rows.length, 0),
  );

  protected setKind(value: InteractiveKind): void {
    this.kind.set(value);
  }

  protected onBodyChange(value: string): void {
    this.body.set(value);
  }

  protected onHeaderChange(value: string): void {
    this.headerText.set(value);
  }

  protected onFooterChange(value: string): void {
    this.footerText.set(value);
  }

  // --- reply buttons -------------------------------------------------

  protected addButton(): void {
    const current = this.buttons();
    if (current.length >= LIMITS.buttonsMax) return;
    this.buttons.set([...current, { id: `btn_${current.length + 1}`, title: '' }]);
  }

  protected removeButton(index: number): void {
    const current = this.buttons();
    if (current.length <= 1) return;
    this.buttons.set(current.filter((_, i) => i !== index));
  }

  protected updateButton(index: number, field: 'id' | 'title', value: string): void {
    this.buttons.set(this.buttons().map((b, i) => (i === index ? { ...b, [field]: value } : b)));
  }

  // --- CTA URL -------------------------------------------------------

  protected onCtaButtonTextChange(value: string): void {
    this.ctaButtonText.set(value);
  }

  protected onCtaUrlChange(value: string): void {
    this.ctaUrl.set(value);
  }

  // --- list ----------------------------------------------------------

  protected onListButtonChange(value: string): void {
    this.listButtonText.set(value);
  }

  protected addSection(): void {
    const current = this.sections();
    if (current.length >= LIMITS.listSectionsMax) return;
    this.sections.set([
      ...current,
      { title: '', rows: [{ id: `row_${this.totalListRows() + 1}`, title: '', description: '' }] },
    ]);
  }

  protected removeSection(index: number): void {
    const current = this.sections();
    if (current.length <= 1) return;
    this.sections.set(current.filter((_, i) => i !== index));
  }

  protected updateSectionTitle(index: number, value: string): void {
    this.sections.set(this.sections().map((s, i) => (i === index ? { ...s, title: value } : s)));
  }

  protected addRow(sectionIndex: number): void {
    if (this.totalListRows() >= LIMITS.listRowsMax) return;
    this.sections.set(
      this.sections().map((s, i) =>
        i === sectionIndex
          ? {
              ...s,
              rows: [
                ...s.rows,
                {
                  id: `row_${this.totalListRows() + 1}`,
                  title: '',
                  description: '',
                },
              ],
            }
          : s,
      ),
    );
  }

  protected removeRow(sectionIndex: number, rowIndex: number): void {
    const section = this.sections()[sectionIndex];
    if (!section || section.rows.length <= 1) return;
    this.sections.set(
      this.sections().map((s, i) =>
        i === sectionIndex ? { ...s, rows: s.rows.filter((_, ri) => ri !== rowIndex) } : s,
      ),
    );
  }

  protected updateRow(
    sectionIndex: number,
    rowIndex: number,
    field: 'id' | 'title' | 'description',
    value: string,
  ): void {
    this.sections.set(
      this.sections().map((s, i) =>
        i === sectionIndex
          ? {
              ...s,
              rows: s.rows.map((r, ri) => (ri === rowIndex ? { ...r, [field]: value } : r)),
            }
          : s,
      ),
    );
  }

  // --- validation + submit ------------------------------------------

  private validate(): string | null {
    const body = this.body().trim();
    if (!body) return 'Body text is required.';
    if (body.length > LIMITS.bodyMax) {
      return `Body must be ${LIMITS.bodyMax} characters or fewer.`;
    }
    const header = this.headerText().trim();
    if (header.length > LIMITS.headerMax) {
      return `Header must be ${LIMITS.headerMax} characters or fewer.`;
    }
    const footer = this.footerText().trim();
    if (footer.length > LIMITS.footerMax) {
      return `Footer must be ${LIMITS.footerMax} characters or fewer.`;
    }

    if (this.kind() === 'reply_buttons') {
      const buttons = this.buttons();
      if (buttons.length === 0) return 'Add at least one button.';
      if (buttons.length > LIMITS.buttonsMax) {
        return `At most ${LIMITS.buttonsMax} reply buttons allowed.`;
      }
      for (const b of buttons) {
        if (!b.title.trim()) return 'Every button needs a title.';
        if (b.title.length > LIMITS.buttonTitleMax) {
          return `Button titles must be ${LIMITS.buttonTitleMax} characters or fewer.`;
        }
        if (!b.id.trim()) return 'Every button needs an id.';
        if (b.id.length > LIMITS.buttonIdMax) {
          return `Button ids must be ${LIMITS.buttonIdMax} characters or fewer.`;
        }
      }
      const ids = buttons.map((b) => b.id);
      if (new Set(ids).size !== ids.length) {
        return 'Button ids must be unique.';
      }
    } else if (this.kind() === 'cta_url') {
      if (!this.ctaButtonText().trim()) return 'Button label is required.';
      if (this.ctaButtonText().length > LIMITS.buttonTitleMax) {
        return `Button label must be ${LIMITS.buttonTitleMax} characters or fewer.`;
      }
      const url = this.ctaUrl().trim();
      if (!url) return 'URL is required.';
      if (!/^https?:\/\/.+/.test(url)) {
        return 'URL must start with http:// or https://.';
      }
      if (url.length > LIMITS.ctaUrlMax) {
        return `URL must be ${LIMITS.ctaUrlMax} characters or fewer.`;
      }
    } else {
      const sections = this.sections();
      if (sections.length === 0) return 'Add at least one section.';
      if (sections.length > LIMITS.listSectionsMax) {
        return `At most ${LIMITS.listSectionsMax} sections allowed.`;
      }
      let totalRows = 0;
      const allIds: string[] = [];
      for (const s of sections) {
        if (!s.title.trim()) return 'Every section needs a title.';
        if (s.title.length > LIMITS.listSectionTitleMax) {
          return `Section titles must be ${LIMITS.listSectionTitleMax} characters or fewer.`;
        }
        if (s.rows.length === 0) return 'Every section needs at least one row.';
        for (const r of s.rows) {
          totalRows += 1;
          if (!r.title.trim()) return 'Every row needs a title.';
          if (r.title.length > LIMITS.listRowTitleMax) {
            return `Row titles must be ${LIMITS.listRowTitleMax} characters or fewer.`;
          }
          if (!r.id.trim()) return 'Every row needs an id.';
          if (r.id.length > LIMITS.listRowIdMax) {
            return `Row ids must be ${LIMITS.listRowIdMax} characters or fewer.`;
          }
          if ((r.description ?? '').length > LIMITS.listRowDescriptionMax) {
            return `Row descriptions must be ${LIMITS.listRowDescriptionMax} characters or fewer.`;
          }
          allIds.push(r.id);
        }
      }
      if (totalRows > LIMITS.listRowsMax) {
        return `At most ${LIMITS.listRowsMax} rows total across sections.`;
      }
      if (new Set(allIds).size !== allIds.length) {
        return 'Row ids must be unique across sections.';
      }
      if (!this.listButtonText().trim()) return 'List button label is required.';
      if (this.listButtonText().length > LIMITS.listButtonMax) {
        return `List button label must be ${LIMITS.listButtonMax} characters or fewer.`;
      }
    }
    return null;
  }

  protected onSubmit(): void {
    if (!this.canSubmit()) return;
    const header = this.headerText().trim();
    const footer = this.footerText().trim();
    const headerBlock = header ? { header: { text: header } } : {};
    const footerBlock = footer ? { footer } : {};

    let payload: InteractivePayload;
    if (this.kind() === 'reply_buttons') {
      payload = {
        kind: 'reply_buttons',
        body: this.body().trim(),
        buttons: this.buttons().map((b) => ({
          id: b.id.trim(),
          title: b.title.trim(),
        })),
        ...headerBlock,
        ...footerBlock,
      } as ReplyButtonsPayload;
    } else if (this.kind() === 'cta_url') {
      payload = {
        kind: 'cta_url',
        body: this.body().trim(),
        button_text: this.ctaButtonText().trim(),
        url: this.ctaUrl().trim(),
        ...headerBlock,
        ...footerBlock,
      } as CtaUrlPayload;
    } else {
      payload = {
        kind: 'list',
        body: this.body().trim(),
        button_text: this.listButtonText().trim(),
        sections: this.sections().map((s) => ({
          title: s.title.trim(),
          rows: s.rows.map((r) => ({
            id: r.id.trim(),
            title: r.title.trim(),
            ...(r.description.trim() ? { description: r.description.trim() } : {}),
          })),
        })),
        ...headerBlock,
        ...footerBlock,
      } as ListPayload;
    }
    this.submit.emit(payload);
    this.reset();
  }

  protected onCancel(): void {
    this.cancel.emit();
    this.reset();
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (this.open) this.onCancel();
  }

  private reset(): void {
    this.body.set('');
    this.headerText.set('');
    this.footerText.set('');
    this.buttons.set([
      { id: 'btn_1', title: '' },
      { id: 'btn_2', title: '' },
    ]);
    this.ctaButtonText.set('');
    this.ctaUrl.set('');
    this.listButtonText.set('Choose');
    this.sections.set([
      {
        title: '',
        rows: [
          { id: 'row_1', title: '', description: '' },
          { id: 'row_2', title: '', description: '' },
        ],
      },
    ]);
    this.kind.set('reply_buttons');
  }
}
