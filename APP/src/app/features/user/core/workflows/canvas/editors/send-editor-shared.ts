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

export const RECIPIENT_PLACEHOLDERS: Readonly<
  Record<string, RecipientOption[]>
> = {};
