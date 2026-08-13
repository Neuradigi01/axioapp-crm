/**
 * Chatbot node-type registry (tasks/chatbot-builder Step 13).
 *
 * Single source of truth for palette metadata (label / icon /
 * category) + graph topology (ports) + default config shape. Read
 * by the palette, the canvas, and every concrete node component.
 *
 * Node types + their exact string keys mirror the backend
 * `core/chatbots/graph.py:NODE_TYPES` set — drift breaks
 * save-time validation.
 */

export type NodeCategory = 'message' | 'action' | 'crm' | 'ai';
export type PaletteTab = 'messages' | 'actions';
export type OutputTopology = 'single' | 'labeled' | 'dynamic';

export interface NodeTypeMeta {
  type: string;
  label: string;
  icon: string;
  category: NodeCategory;
  paletteTab: PaletteTab;
  /** `single` = one default out edge; `labeled` = fixed named ports
   *  (answered / invalid / timeout / true / false / …); `dynamic` =
   *  one port per button/row configured on the node. */
  outputs: OutputTopology;
  /** Labelled port names for `outputs: 'labeled'` topology. */
  labels?: readonly string[];
  /** Empty-state / marketing description for the palette tile. */
  hint: string;
  /** v1 gating — commerce + AI nodes are visible but their runtime
   *  is a stub (`error` port only). Frontend renders a "Beta" chip. */
  beta?: boolean;
  /** Default config the palette drops onto the canvas. */
  defaultConfig: Record<string, unknown>;
}

// prettier-ignore
export const NODE_TYPES: readonly NodeTypeMeta[] = [
  // --- Messages tab (7) ---
  {
    type: 'text_button', label: 'Text Button', icon: 'list',
    category: 'message', paletteTab: 'messages', outputs: 'dynamic',
    hint: 'Send a message with up to 3 reply buttons.',
    defaultConfig: {
      body: 'How can I help?',
      buttons: [{ id: 'yes', title: 'Yes' }, { id: 'no', title: 'No' }],
    },
  },
  {
    type: 'media_button', label: 'Media Button', icon: 'image',
    category: 'message', paletteTab: 'messages', outputs: 'dynamic',
    hint: 'Send an image / video / doc + reply buttons.',
    defaultConfig: {
      body: 'Take a look:',
      header_media: { type: 'image', media_id: '' },
      buttons: [{ id: 'yes', title: 'Yes' }, { id: 'no', title: 'No' }],
    },
  },
  {
    type: 'list', label: 'List', icon: 'list',
    category: 'message', paletteTab: 'messages', outputs: 'dynamic',
    hint: 'Send a selectable list (up to 10 rows).',
    defaultConfig: {
      body: 'Pick one:', button_text: 'Choose',
      sections: [{ title: 'Options', rows: [
        { id: 'a', title: 'Option A' }, { id: 'b', title: 'Option B' },
      ] }],
    },
  },
  {
    type: 'catalog_message', label: 'Catalog', icon: 'file-text',
    category: 'message', paletteTab: 'messages', outputs: 'single', beta: true,
    hint: 'WA Business Commerce catalog (requires setup).',
    defaultConfig: {},
  },
  {
    type: 'single_product', label: 'Single Product', icon: 'package',
    category: 'message', paletteTab: 'messages', outputs: 'single', beta: true,
    hint: 'Show one product card (requires WA Commerce).',
    defaultConfig: {},
  },
  {
    type: 'multi_product', label: 'Multi Product', icon: 'package',
    category: 'message', paletteTab: 'messages', outputs: 'single', beta: true,
    hint: 'Show multiple products (requires WA Commerce).',
    defaultConfig: {},
  },
  {
    type: 'template', label: 'Template', icon: 'file-text',
    category: 'message', paletteTab: 'messages', outputs: 'single',
    hint: 'Send an approved WA / Email template.',
    defaultConfig: { template_id: '', variables: {} },
  },

  // --- Actions tab · Ask-* (4) ---
  {
    type: 'ask_question', label: 'Ask Question', icon: 'pencil',
    category: 'action', paletteTab: 'actions', outputs: 'labeled',
    labels: ['answered', 'invalid', 'timeout'],
    hint: 'Ask, validate, save the answer to a contact / lead field.',
    defaultConfig: {
      prompt: "What's your name?", save_to: 'contact.full_name',
      expected_format: 'text', max_retries: 2, timeout_seconds: 79200,
      retry_message: "Sorry, I didn't catch that — please try again.",
    },
  },
  {
    type: 'ask_address', label: 'Ask Address', icon: 'map-pin',
    category: 'action', paletteTab: 'actions', outputs: 'labeled',
    labels: ['answered', 'timeout'],
    hint: 'Ask for a postal address; parses street / city / postal.',
    defaultConfig: {
      prompt: "What's your address?", save_to: 'contact.custom.address',
      timeout_seconds: 79200,
    },
  },
  {
    type: 'ask_location', label: 'Ask Location', icon: 'map-pin',
    category: 'action', paletteTab: 'actions', outputs: 'labeled',
    labels: ['answered', 'invalid', 'timeout'],
    hint: 'Ask for a geo-location (WA pin or lat, lng).',
    defaultConfig: {
      prompt: 'Where should we deliver?', save_to: 'contact.custom.location',
      timeout_seconds: 79200, max_retries: 2,
    },
  },
  {
    type: 'ask_media', label: 'Ask Media', icon: 'paperclip',
    category: 'action', paletteTab: 'actions', outputs: 'labeled',
    labels: ['answered', 'invalid', 'timeout'],
    hint: 'Ask for a file / image / video upload.',
    defaultConfig: {
      prompt: 'Please upload the file.',
      save_to: 'contact.custom.uploaded_file_id',
      max_size_bytes: 10485760, allowed_types: ['image', 'document'],
      timeout_seconds: 79200, max_retries: 2,
    },
  },

  // --- Actions tab · Utility (5) ---
  {
    type: 'condition', label: 'Condition', icon: 'git-branch',
    category: 'action', paletteTab: 'actions', outputs: 'labeled',
    labels: ['true', 'false'],
    hint: 'If / else based on answers, contact, or run scope.',
    defaultConfig: {
      condition: {
        op: 'equals', left: { path: 'answers.foo' }, right: { value: '' },
      },
    },
  },
  {
    type: 'delay', label: 'Delay', icon: 'clock',
    category: 'action', paletteTab: 'actions', outputs: 'single',
    hint: 'Pause for N seconds / minutes / hours / days.',
    defaultConfig: { amount: 5, unit: 'minutes' },
  },
  {
    type: 'add_tag', label: 'Add Tag', icon: 'tag',
    category: 'action', paletteTab: 'actions', outputs: 'single',
    hint: 'Add or remove tags on the contact.',
    defaultConfig: { entity: 'contact', operation: 'add', tags: [] },
  },
  {
    type: 'set_custom_field', label: 'Set Custom Field', icon: 'pencil',
    category: 'action', paletteTab: 'actions', outputs: 'single',
    hint: 'Write a static or templated value to a field.',
    defaultConfig: { save_to: 'contact.custom.', value: '' },
  },
  {
    type: 'api_request', label: 'API Request', icon: 'globe',
    category: 'action', paletteTab: 'actions', outputs: 'labeled',
    labels: ['success', 'error'],
    hint: 'Call an external HTTPS API (SSRF-safe).',
    defaultConfig: {
      method: 'GET', url: 'https://', headers: {},
      body_template: null, timeout_seconds: 10, capture: {},
    },
  },

  // --- Actions tab · CRM extras (4) ---
  {
    type: 'handoff_to_human', label: 'Handoff to Human', icon: 'bot',
    category: 'crm', paletteTab: 'actions', outputs: 'single',
    hint: 'Assign the conversation to a teammate + end the bot run.',
    defaultConfig: {
      assign_mode: 'specific', user_id: null,
      final_bot_message: 'A team member will jump in shortly.',
    },
  },
  {
    type: 'create_lead', label: 'Create Lead', icon: 'target',
    category: 'crm', paletteTab: 'actions', outputs: 'labeled',
    labels: ['created', 'error'],
    hint: 'Create a lead from captured answers + contact context.',
    defaultConfig: {
      source: 'chatbot', budget_from: '', expected_close_date_from: '',
      pipeline_stage: null, custom_field_map: {},
    },
  },
  {
    type: 'book_appointment', label: 'Book Appointment', icon: 'calendar',
    category: 'crm', paletteTab: 'actions', outputs: 'labeled',
    labels: ['booked', 'busy', 'error'],
    hint: 'Book a slot on a teammate\'s calendar.',
    defaultConfig: {
      title_template: 'Bot appointment for {{contact.full_name}}',
      duration_minutes: 30, scheduled_at_from: 'answers.slot',
      assigned_to_user_id: '',
    },
  },
  {
    type: 'create_task', label: 'Create Task', icon: 'target',
    category: 'crm', paletteTab: 'actions', outputs: 'labeled',
    labels: ['created', 'error'],
    hint: 'Create a follow-up task for the assignee.',
    defaultConfig: {
      title: 'Follow up with {{contact.full_name}}',
      assignee_mode: 'contact_owner', due_in_hours: 24, priority: 'medium',
    },
  },

  // --- Actions tab · Flow + AI (3) ---
  {
    type: 'connect_flow', label: 'Connect Flow', icon: 'git-branch',
    category: 'action', paletteTab: 'actions', outputs: 'labeled',
    labels: ['error'],
    hint: 'Chain into another bot with answers passed through.',
    defaultConfig: { target_bot_id: '' },
  },
  {
    type: 'single_ai_message', label: 'AI Message', icon: 'bot',
    category: 'ai', paletteTab: 'actions', outputs: 'labeled', beta: true,
    labels: ['sent', 'error'],
    hint: 'One-shot LLM reply (requires AI provider setup).',
    defaultConfig: {
      system_prompt: 'You are a helpful assistant.',
      user_prompt_template: '{{run.last_inbound_text}}',
      max_tokens: 400, temperature: 0.4, save_reply_to: 'answers.ai_reply',
    },
  },
  {
    type: 'assign_ai_assistant', label: 'AI Assistant', icon: 'bot',
    category: 'ai', paletteTab: 'actions', outputs: 'labeled', beta: true,
    labels: ['handed_off', 'error'],
    hint: 'Hand off to an ongoing LLM assistant (requires setup).',
    defaultConfig: {
      assistant_id: '', system_prompt: '',
      max_turns: 8, handoff_on_low_confidence: true,
    },
  },
] as const;

export function getNodeType(type: string): NodeTypeMeta | undefined {
  return NODE_TYPES.find((n) => n.type === type);
}

export function nodesByTab(tab: PaletteTab): NodeTypeMeta[] {
  return NODE_TYPES.filter((n) => n.paletteTab === tab);
}
