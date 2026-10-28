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
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import {
  WhatsAppTemplateButton,
  WhatsAppTemplateButtonType,
  WhatsAppTemplateCategory,
  WhatsAppTemplateHeaderType,
  WhatsAppTemplateRead,
  WhatsAppTemplateUpsert,
} from './whatsapp-templates-api.service';
import { TemplatePreviewComponent } from './template-preview.component';

/**
 * Multi-step template create / edit wizard
 * (whatsapp-platform-upgrade Step 9).
 *
 * Steps:
 *   1. Basics — name, language, category
 *   2. Header — optional TEXT / IMAGE / VIDEO / DOCUMENT
 *   3. Body — variable-aware textarea (`{{1}}`, `{{2}}`)
 *   4. Footer — optional short text
 *   5. Buttons — Quick Reply (max 3) OR CTA (URL / PHONE), never both
 *   6. Samples — one input per `{{n}}` placeholder; drives preview
 *   7. Review — read-only summary + submit
 *
 * State lives in component signals; the live preview pane on the
 * right subscribes via the same signals so every keystroke rerenders.
 * Validation matches the backend `WhatsAppTemplateUpsert` rules — a
 * draft that passes here will pass the backend's Pydantic check too.
 */

// Mirror of backend caps in `core/integrations/whatsapp/schemas.py`.
// Keep in lockstep — see Step 8.
const LIMITS = {
  nameMax: 512,
  bodyMax: 1024,
  headerMax: 60,
  footerMax: 60,
  buttonTextMax: 25,
  buttonsMax: 10,
  ctaUrlMax: 2000,
  ctaPhoneMax: 20,
};

const LANGUAGES: Array<{ code: string; label: string }> = [
  { code: 'en_US', label: 'English (US)' },
  { code: 'en_GB', label: 'English (UK)' },
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'Hindi' },
  { code: 'gu', label: 'Gujarati' },
  { code: 'mr', label: 'Marathi' },
  { code: 'ta', label: 'Tamil' },
  { code: 'te', label: 'Telugu' },
  { code: 'bn', label: 'Bengali' },
];

type ButtonGroup = 'NONE' | 'QUICK_REPLY' | 'CTA';

@Component({
  selector: 'app-template-wizard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule, TemplatePreviewComponent],
  templateUrl: './template-wizard.component.html',
})
export class TemplateWizardComponent {
  /** Existing row to edit. When null, the wizard creates a new draft. */
  @Input() set initialTemplate(value: WhatsAppTemplateRead | null) {
    if (value) {
      this.hydrateFrom(value);
      this.editingId.set(value.id);
    } else {
      this.editingId.set(null);
    }
  }

  /** Submission state — drives the disabled-on-submit affordance. */
  @Input() submitting = false;
  /** Server-side error message (after backend Pydantic rejection). */
  @Input() serverError: string | null = null;

  @Output() readonly submit = new EventEmitter<WhatsAppTemplateUpsert>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly LIMITS = LIMITS;
  protected readonly LANGUAGES = LANGUAGES;
  protected readonly editingId = signal<string | null>(null);

  protected readonly step = signal<number>(1);
  protected readonly maxStep = 7;

  // Step 1
  protected readonly name = signal('');
  protected readonly language = signal('en_US');
  protected readonly category = signal<WhatsAppTemplateCategory>('MARKETING');

  // Step 2
  protected readonly headerType = signal<WhatsAppTemplateHeaderType | null>(null);
  protected readonly headerText = signal('');

  // Step 3
  protected readonly body = signal('');

  // Step 4
  protected readonly footerText = signal('');

  // Step 5
  protected readonly buttonGroup = signal<ButtonGroup>('NONE');
  protected readonly quickReplyButtons = signal<string[]>([]);
  protected readonly ctaButtons = signal<WhatsAppTemplateButton[]>([]);

  // Step 6 — sample values keyed by variable number ({{1}} → key 1)
  protected readonly sampleValues = signal<Record<number, string>>({});

  // --- derived state -----------------------------------------------

  protected readonly variableSlots = computed<number[]>(() => {
    const matches = this.body().match(/\{\{(\d+)\}\}/g) || [];
    const set = new Set<number>();
    for (const m of matches) {
      const n = Number(m.replace(/\{\{|\}\}/g, ''));
      if (!Number.isNaN(n)) set.add(n);
    }
    return Array.from(set).sort((a, b) => a - b);
  });

  protected readonly bodyChars = computed(() => this.body().length);

  protected readonly assembledButtons = computed<WhatsAppTemplateButton[]>(() => {
    const group = this.buttonGroup();
    if (group === 'QUICK_REPLY') {
      return this.quickReplyButtons()
        .filter((t) => t.trim().length > 0)
        .map((text) => ({
          type: 'QUICK_REPLY' as WhatsAppTemplateButtonType,
          text,
        }));
    }
    if (group === 'CTA') {
      return this.ctaButtons().filter((b) => b.text.trim().length > 0);
    }
    return [];
  });

  protected readonly nameError = computed(() => {
    const n = this.name().trim();
    if (!n) return 'Name is required.';
    if (n.length > LIMITS.nameMax) {
      return `Name must be ${LIMITS.nameMax} characters or fewer.`;
    }
    if (!/^[a-z0-9_]+$/.test(n)) {
      return 'Name must be lowercase letters, numbers, and underscores only.';
    }
    return null;
  });

  protected readonly bodyError = computed(() => {
    const b = this.body();
    if (!b.trim()) return 'Body is required.';
    if (b.length > LIMITS.bodyMax) {
      return `Body must be ${LIMITS.bodyMax} characters or fewer.`;
    }
    return null;
  });

  protected readonly headerError = computed(() => {
    const t = this.headerType();
    const text = this.headerText().trim();
    if (t === 'TEXT' && !text) {
      return 'TEXT header requires text.';
    }
    if (t === 'TEXT' && text.length > LIMITS.headerMax) {
      return `Header must be ${LIMITS.headerMax} characters or fewer.`;
    }
    return null;
  });

  protected readonly buttonsError = computed(() => {
    const group = this.buttonGroup();
    if (group === 'QUICK_REPLY') {
      const present = this.quickReplyButtons().filter((t) => t.trim().length > 0);
      if (present.length === 0) return 'Add at least one button or pick "None".';
      if (present.length > 3) return 'Maximum 3 quick-reply buttons.';
      const tooLong = present.find((t) => t.length > LIMITS.buttonTextMax);
      if (tooLong) return `Each button title must be ${LIMITS.buttonTextMax} characters or fewer.`;
    }
    if (group === 'CTA') {
      const buttons = this.ctaButtons();
      if (buttons.length === 0) return 'Add at least one CTA button or pick "None".';
      for (const b of buttons) {
        if (!b.text.trim()) return 'Every CTA button needs a label.';
        if (b.type === 'URL' && !b.url) return 'URL buttons need a URL.';
        if (b.type === 'PHONE_NUMBER' && !b.phone_number) {
          return 'Phone-number buttons need a number.';
        }
      }
    }
    return null;
  });

  protected readonly samplesError = computed(() => {
    const slots = this.variableSlots();
    const samples = this.sampleValues();
    const missing = slots.find((n) => !samples[n] || !samples[n].trim());
    return missing
      ? `Sample for {{${missing}}} is required so reviewers can see the rendered text.`
      : null;
  });

  protected readonly canAdvance = computed(() => {
    switch (this.step()) {
      case 1:
        return this.nameError() === null && this.language().length > 0;
      case 2:
        return this.headerError() === null;
      case 3:
        return this.bodyError() === null;
      case 4:
        return this.footerText().length <= LIMITS.footerMax;
      case 5:
        return this.buttonsError() === null;
      case 6:
        return this.samplesError() === null;
      default:
        return true;
    }
  });

  protected readonly canSubmit = computed(
    () =>
      this.nameError() === null &&
      this.headerError() === null &&
      this.bodyError() === null &&
      this.buttonsError() === null &&
      this.samplesError() === null &&
      this.footerText().length <= LIMITS.footerMax,
  );

  // --- step navigation ---------------------------------------------

  protected goNext(): void {
    if (!this.canAdvance()) return;
    this.step.update((s) => Math.min(s + 1, this.maxStep));
  }

  protected goPrev(): void {
    this.step.update((s) => Math.max(s - 1, 1));
  }

  // --- body helpers ------------------------------------------------

  protected insertVariable(): void {
    const slots = this.variableSlots();
    const next = (slots[slots.length - 1] ?? 0) + 1;
    this.body.update((b) => `${b}{{${next}}}`);
  }

  // --- header type -------------------------------------------------

  protected pickHeaderType(t: WhatsAppTemplateHeaderType | null): void {
    this.headerType.set(t);
    if (t !== 'TEXT') {
      this.headerText.set('');
    }
  }

  // --- buttons -----------------------------------------------------

  protected pickButtonGroup(group: ButtonGroup): void {
    this.buttonGroup.set(group);
    if (group === 'NONE') {
      this.quickReplyButtons.set([]);
      this.ctaButtons.set([]);
    } else if (group === 'QUICK_REPLY' && this.quickReplyButtons().length === 0) {
      this.quickReplyButtons.set(['']);
    } else if (group === 'CTA' && this.ctaButtons().length === 0) {
      this.ctaButtons.set([{ type: 'URL', text: '', url: '' }]);
    }
  }

  protected addQuickReply(): void {
    if (this.quickReplyButtons().length >= 3) return;
    this.quickReplyButtons.update((arr) => [...arr, '']);
  }

  protected removeQuickReply(idx: number): void {
    this.quickReplyButtons.update((arr) => arr.filter((_, i) => i !== idx));
  }

  protected updateQuickReply(idx: number, value: string): void {
    this.quickReplyButtons.update((arr) => arr.map((v, i) => (i === idx ? value : v)));
  }

  protected addCta(): void {
    if (this.ctaButtons().length >= 2) return;
    this.ctaButtons.update((arr) => [...arr, { type: 'URL', text: '', url: '' }]);
  }

  protected removeCta(idx: number): void {
    this.ctaButtons.update((arr) => arr.filter((_, i) => i !== idx));
  }

  protected updateCta(idx: number, patch: Partial<WhatsAppTemplateButton>): void {
    this.ctaButtons.update((arr) => arr.map((b, i) => (i === idx ? { ...b, ...patch } : b)));
  }

  // --- samples -----------------------------------------------------

  protected updateSample(n: number, value: string): void {
    this.sampleValues.update((s) => ({ ...s, [n]: value }));
  }

  // --- submit ------------------------------------------------------

  protected onSubmit(): void {
    if (!this.canSubmit()) return;
    const payload: WhatsAppTemplateUpsert = {
      name: this.name().trim(),
      language: this.language(),
      category: this.category(),
      body: this.body(),
      header_type: this.headerType(),
      header_text: this.headerType() === 'TEXT' ? this.headerText().trim() || null : null,
      footer_text: this.footerText().trim() || null,
      buttons: this.assembledButtons(),
    };
    this.submit.emit(payload);
  }

  protected onCancel(): void {
    this.cancel.emit();
  }

  // --- hydration ---------------------------------------------------

  private hydrateFrom(row: WhatsAppTemplateRead): void {
    this.name.set(row.name);
    this.language.set(row.language);
    this.category.set((row.category as WhatsAppTemplateCategory) || 'MARKETING');
    this.headerType.set((row.header_type as WhatsAppTemplateHeaderType) || null);
    this.headerText.set(row.header_text || '');
    this.body.set(row.body);
    this.footerText.set(row.footer_text || '');

    // Rehydrate buttons from `body_components` if present.
    const buttonsComponent = (row.body_components || []).find(
      (c) => (c as { type?: string }).type === 'BUTTONS',
    ) as { buttons?: WhatsAppTemplateButton[] } | undefined;
    const buttons = buttonsComponent?.buttons ?? [];
    if (buttons.length === 0) {
      this.pickButtonGroup('NONE');
    } else if (buttons.every((b) => b.type === 'QUICK_REPLY')) {
      this.buttonGroup.set('QUICK_REPLY');
      this.quickReplyButtons.set(buttons.map((b) => b.text));
    } else {
      this.buttonGroup.set('CTA');
      this.ctaButtons.set(
        buttons.map((b) => ({
          type: b.type,
          text: b.text,
          url: b.url ?? '',
          phone_number: b.phone_number ?? '',
        })),
      );
    }
    this.step.set(1);
  }
}
