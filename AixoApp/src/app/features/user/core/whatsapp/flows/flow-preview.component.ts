import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

interface FlowScreen {
  id: string;
  title: string;
  layout?: {
    children?: Array<Record<string, unknown>>;
  };
}

interface FlowDefinition {
  screens?: FlowScreen[];
}

interface FlowField {
  type: string;
  name?: string;
  label?: string;
  required?: boolean;
  helperText?: string;
  options?: string[];
}

/**
 * Step 25 — read-only WhatsApp Flow JSON renderer.
 *
 * Shows the screen list + the fields on each screen so an operator
 * can sanity-check the JSON before publishing. Doesn't try to be a
 * pixel-perfect WhatsApp client — just enough to confirm "yes,
 * those are the inputs the customer will see."
 *
 * Recognised input types are the subset the bundled templates use:
 * ``TextInput`` / ``TextArea`` / ``Dropdown`` / ``DatePicker`` /
 * ``CheckboxGroup``. Anything else renders as a generic tag with
 * the raw type label so future Meta-side additions don't crash the
 * preview.
 */
@Component({
  selector: 'app-flow-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    <div class="rounded-md border border-subtle bg-surface p-3">
      <p class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
        Preview ({{ screens().length }} screen{{ screens().length === 1 ? '' : 's' }})
      </p>
      @for (screen of screens(); track screen.id; let i = $index) {
        <div class="mb-3 rounded border border-subtle bg-surface-2 p-3">
          <p class="mb-2 text-xs font-semibold text-default">{{ i + 1 }}. {{ screen.title }}</p>
          <ul class="space-y-1.5 text-xs">
            @for (field of screenFields(screen); track field.name || field.type) {
              <li class="flex items-start gap-2">
                <span
                  class="mt-0.5 inline-flex shrink-0 items-center rounded-full bg-violet-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-violet-700 ring-1 ring-violet-200"
                >
                  {{ humanType(field.type) }}
                </span>
                <span class="flex flex-col">
                  <span class="font-medium text-default">
                    {{ field.label || field.name || '(no label)' }}
                    @if (field.required) {
                      <span class="text-red-500">*</span>
                    }
                  </span>
                  @if (field.helperText) {
                    <span class="text-[11px] text-muted">
                      {{ field.helperText }}
                    </span>
                  }
                  @if (field.options && field.options.length > 0) {
                    <span class="text-[11px] text-muted">
                      Options: {{ field.options.join(', ') }}
                    </span>
                  }
                </span>
              </li>
            } @empty {
              <li class="text-[11px] text-muted">(no input fields on this screen)</li>
            }
          </ul>
        </div>
      } @empty {
        <p class="text-[11px] text-muted">Empty flow — add a screen to get started.</p>
      }
    </div>
  `,
})
export class FlowPreviewComponent {
  readonly definition = input.required<Record<string, unknown>>();

  protected readonly screens = computed<FlowScreen[]>(() => {
    const def = this.definition() as FlowDefinition;
    return Array.isArray(def?.screens) ? def.screens : [];
  });

  protected screenFields(screen: FlowScreen): FlowField[] {
    const children = screen.layout?.children ?? [];
    const out: FlowField[] = [];
    this.walkChildren(children, out);
    return out;
  }

  private walkChildren(nodes: Array<Record<string, unknown>>, out: FlowField[]): void {
    for (const node of nodes) {
      const type = String(node['type'] ?? '');
      if (type === 'Form' || type === 'SingleColumnLayout') {
        const inner = node['children'];
        if (Array.isArray(inner)) {
          this.walkChildren(inner as Array<Record<string, unknown>>, out);
        }
        continue;
      }
      if (type === 'Footer' || type === 'TextHeading' || type === 'TextBody') {
        continue;
      }
      const dataSource = node['data-source'];
      const options = Array.isArray(dataSource)
        ? (dataSource as Array<Record<string, unknown>>)
            .map((o) => String(o['title'] ?? o['id'] ?? ''))
            .filter((s) => s.length > 0)
            .slice(0, 6)
        : undefined;
      out.push({
        type,
        name: node['name'] ? String(node['name']) : undefined,
        label: node['label'] ? String(node['label']) : undefined,
        required: node['required'] === true || node['required'] === 'true',
        helperText: node['helper-text'] ? String(node['helper-text']) : undefined,
        options,
      });
    }
  }

  protected humanType(type: string): string {
    switch (type) {
      case 'TextInput':
        return 'Text';
      case 'TextArea':
        return 'Paragraph';
      case 'Dropdown':
        return 'Dropdown';
      case 'DatePicker':
        return 'Date';
      case 'CheckboxGroup':
        return 'Multi-select';
      case 'RadioButtonsGroup':
        return 'Radio';
      default:
        return type || 'field';
    }
  }
}
