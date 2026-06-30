import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  input,
  output,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CanvasNode } from '../canvas-state.service';


@Component({
  selector: 'app-webhook-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './webhook-editor.component.html',
})
export class WebhookEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly configChange = output<Record<string, unknown>>();
  readonly validityChange = output<boolean>();

  // Pre-built string so the template binds via `[placeholder]` without
  // Angular trying to interpolate the literal `{{...}}` tokens it
  // contains.
  readonly bodyPlaceholder =
    '{"contact_id": "{{contact.id}}", "score": "{{lead.lead_score}}"}';

  readonly url = computed<string>(
    () => (this.node().config?.['url'] as string) ?? '',
  );
  readonly method = computed<string>(
    () => (this.node().config?.['method'] as string) ?? 'POST',
  );
  readonly body = computed<string>(
    () => (this.node().config?.['body'] as string) ?? '',
  );
  readonly headers = computed<string>(
    () => (this.node().config?.['headers'] as string) ?? '',
  );
  readonly expectedStatuses = computed<string>(
    () => (this.node().config?.['expected_status_codes'] as string) ?? '200,201,202,204',
  );
  readonly onFailure = computed<string>(
    () => (this.node().config?.['on_failure'] as string) ?? 'skip',
  );

  constructor() {
    effect(() => {
      const ok = /^https:\/\//i.test(this.url().trim());
      this.validityChange.emit(ok);
    });
  }

  onUrlChange(v: string): void { this.configChange.emit({ url: v }); }
  onMethodChange(v: string): void { this.configChange.emit({ method: v }); }
  onBodyChange(v: string): void { this.configChange.emit({ body: v }); }
  onHeadersChange(v: string): void { this.configChange.emit({ headers: v }); }
  onStatusChange(v: string): void { this.configChange.emit({ expected_status_codes: v }); }
  onFailureChange(v: string): void { this.configChange.emit({ on_failure: v }); }

  isValidUrl(): boolean {
    return /^https:\/\//i.test(this.url().trim());
  }
}
