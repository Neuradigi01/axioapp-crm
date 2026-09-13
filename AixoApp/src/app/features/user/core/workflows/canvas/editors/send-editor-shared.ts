/**
 * Shared logic for the 7 send editors. Each channel editor (email,
 * whatsapp, sms, fb, ig, push, slack) reads `template_id` + recipient +
 * category from `node.config` and emits patches via the same shape.
 *
 * Differences per channel:
 *   - email: tracking flags (`track_opens` / `track_clicks`)
 *   - whatsapp: filters to Meta-approved templates only
 *   - sms / fb / ig / push: no extras
 *   - slack: `slack_channel` instead of recipient
 */

import { CanvasNode } from '../canvas-state.service';
import { TemplateRead } from '../../../templates/templates-api.service';
import { MobileSelectOption } from '../../../shared/forms/mobile-select.component';
import { RecipientOption, SEND_CATEGORIES } from './editor-contract';

export interface SendEditorState {
  templateId: string;
  recipient: string;
  customRecipient: string;
  category: string;
}

export function readSendState(node: CanvasNode): SendEditorState {
  const cfg = node.config ?? {};
  return {
    templateId: (cfg['template_id'] as string) ?? '',
    recipient: (cfg['recipient'] as string) ?? '',
    customRecipient: (cfg['recipient_custom'] as string) ?? '',
    category: (cfg['category'] as string) ?? 'marketing',
  };
}

/** Required-fields validity. Custom recipient → also need the path
 *  string filled in. */
export function sendIsValid(state: SendEditorState): boolean {
  if (!state.templateId) return false;
  if (!state.recipient) return false;
  if (state.recipient === 'custom' && !state.customRecipient.trim()) {
    return false;
  }
  return true;
}

export const SEND_CATEGORY_OPTIONS = SEND_CATEGORIES;

export const RECIPIENT_PLACEHOLDERS: Readonly<Record<string, RecipientOption[]>> = {};

/** Build the `<crm-mobile-select>` option list for a template picker.
 *
 * Guarantees the currently-selected `templateId` is always present in
 * the returned options — even when it's not in `tpls` (deleted /
 * archived / not in the paginated fetch / channel-filtered out).
 * Without this fallback, `<crm-mobile-select>` shows the "— pick a
 * template —" placeholder instead of the stored value, and the operator
 * sees an empty picker on a workflow that IS configured.
 *
 * Pass `null` for `tpls` while the list is still loading so the picker
 * shows only the placeholder + fallback (if any) instead of a stale
 * option set.
 */
export function buildTemplateOptions(
  tpls: TemplateRead[] | null,
  currentId: string,
  labelFor: (t: TemplateRead) => string = (t) => (t.subject ? `${t.name} — ${t.subject}` : t.name),
): MobileSelectOption[] {
  const options: MobileSelectOption[] = [{ value: '', label: '— pick a template —' }];
  if (tpls) {
    for (const t of tpls) options.push({ value: t.id, label: labelFor(t) });
  }
  if (currentId && !tpls?.some((t) => t.id === currentId)) {
    // Selected template isn't in the fetched list — surface a fallback
    // option so the operator can see something is selected. The short
    // id keeps it recognisable without exposing the full UUID.
    options.push({
      value: currentId,
      label: `(unlisted template · ${currentId.slice(0, 8)}…)`,
    });
  }
  return options;
}
