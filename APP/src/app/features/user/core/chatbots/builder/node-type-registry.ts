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

/**
 * Schema-driven form field descriptor. One field per `configSchema`
 * entry; the `NodeConfigFormComponent` renders any schema uniformly.
 *
 * `key` uses dot notation (`header_media.type`) so nested defaults
 * flatten cleanly. Nested arrays of primitives are handled by the
 * `string_list` field; nested arrays of objects (buttons, list rows)
 * are handled by dedicated repeaters (`button_list`, `list_rows`).
 * Complex-shape fields without a dedicated renderer fall back to a
 * per-field JSON textarea via `type: 'json'`.
 */
export type FieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'select'
  | 'boolean'
  | 'string_list'
  | 'button_list'
  | 'json';

export interface FieldSchema {
  key: string;
  label: string;
  type: FieldType;
  help?: string;
  placeholder?: string;
  options?: readonly { value: string; label: string }[];
  min?: number;
  max?: number;
  step?: number;
  rows?: number;
  maxLength?: number;
  /** Cap for `button_list` / `string_list` (e.g. WA text_button = 3 buttons). */
  maxItems?: number;
  /** Show a red asterisk next to the label so the operator knows the
   *  backend will reject a Save with this field empty. Purely visual —
   *  actual validation stays on the backend so the two never drift. */
  required?: boolean;
}

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
  /** Form fields rendered on the node card. When absent the node
   *  falls back to a raw-JSON textarea (transitional — every node
   *  gets a schema in the follow-up push). */
  configSchema?: readonly FieldSchema[];
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
    configSchema: [
      { key: 'body', label: 'Message', type: 'textarea', rows: 3, maxLength: 1024,
        placeholder: 'Enter message here', help: 'Max 1024 characters.', required: true },
      { key: 'buttons', label: 'Buttons', type: 'button_list', maxItems: 3,
        help: 'Up to 3 reply buttons. Each button becomes an output port.', required: true },
    ],
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
    configSchema: [
      { key: 'header_media.type', label: 'Media type', type: 'select', options: [
        { value: 'image', label: 'Image' }, { value: 'video', label: 'Video' },
        { value: 'document', label: 'Document' },
      ] },
      { key: 'header_media.media_id', label: 'Media ID', type: 'text',
        placeholder: 'WA media ID or file token',
        help: 'Upload flow lands in a follow-up; paste an ID for now.' },
      { key: 'body', label: 'Message', type: 'textarea', rows: 3, maxLength: 1024, required: true },
      { key: 'buttons', label: 'Buttons', type: 'button_list', maxItems: 3, required: true },
    ],
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
    configSchema: [
      { key: 'body', label: 'Body', type: 'textarea', rows: 2, maxLength: 1024,
        placeholder: 'Pick one:' },
      { key: 'button_text', label: 'Button label', type: 'text', maxLength: 20,
        placeholder: 'Choose', help: 'Text on the WA "open list" button. Max 20 chars.' },
      { key: 'sections', label: 'Sections + rows', type: 'json',
        help: 'Array of { title, rows: [{id, title, description?}] }. Section editor UI lands in a follow-up.' },
    ],
  },
  {
    type: 'catalog_message', label: 'Catalog', icon: 'file-text',
    category: 'message', paletteTab: 'messages', outputs: 'single', beta: true,
    hint: 'WA Business Commerce catalog (requires setup).',
    defaultConfig: {},
    configSchema: [
      { key: 'body', label: 'Body', type: 'textarea', rows: 2, maxLength: 1024,
        placeholder: 'Check out our catalog:' },
      { key: 'catalog_id', label: 'Catalog ID', type: 'text',
        placeholder: 'Meta Commerce catalog ID',
        help: 'Runtime is stubbed in v1 — save the ID; wiring lands when WA Commerce setup is finished.' },
    ],
  },
  {
    type: 'single_product', label: 'Single Product', icon: 'package',
    category: 'message', paletteTab: 'messages', outputs: 'single', beta: true,
    hint: 'Show one product card (requires WA Commerce).',
    defaultConfig: {},
    configSchema: [
      { key: 'body', label: 'Body', type: 'textarea', rows: 2, maxLength: 1024 },
      { key: 'catalog_id', label: 'Catalog ID', type: 'text',
        placeholder: 'Meta Commerce catalog ID' },
      { key: 'product_retailer_id', label: 'Product ID', type: 'text',
        placeholder: 'Retailer product ID',
        help: 'Runtime is stubbed in v1 — see WA Commerce setup.' },
    ],
  },
  {
    type: 'multi_product', label: 'Multi Product', icon: 'package',
    category: 'message', paletteTab: 'messages', outputs: 'single', beta: true,
    hint: 'Show multiple products (requires WA Commerce).',
    defaultConfig: {},
    configSchema: [
      { key: 'body', label: 'Body', type: 'textarea', rows: 2, maxLength: 1024 },
      { key: 'catalog_id', label: 'Catalog ID', type: 'text',
        placeholder: 'Meta Commerce catalog ID' },
      { key: 'product_retailer_ids', label: 'Product IDs', type: 'string_list',
        placeholder: 'Retailer product ID, press Enter', maxItems: 30,
        help: 'Up to 30 products across sections. Runtime is stubbed in v1.' },
    ],
  },
  {
    type: 'template', label: 'Template', icon: 'file-text',
    category: 'message', paletteTab: 'messages', outputs: 'single',
    hint: 'Send an approved WA / Email template.',
    defaultConfig: { template_id: '', variables: {} },
    configSchema: [
      { key: 'template_id', label: 'Template ID', type: 'text',
        placeholder: 'UUID of an approved template',
        help: 'Pick from /user/templates → Templates → copy ID.' },
      { key: 'variables', label: 'Variables', type: 'json',
        help: 'Object mapping template variable names to values or {{expressions}}.' },
    ],
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
    configSchema: [
      { key: 'prompt', label: 'Question', type: 'textarea', rows: 2, maxLength: 1024,
        placeholder: "e.g. What's your name?", required: true },
      { key: 'save_to', label: 'Save answer to', type: 'text',
        placeholder: 'contact.full_name', required: true,
        help: 'Field path: contact.<field> or lead.<field> or contact.custom.<key>.' },
      { key: 'expected_format', label: 'Expected format', type: 'select', options: [
        { value: 'text', label: 'Free text' }, { value: 'email', label: 'Email' },
        { value: 'phone', label: 'Phone number' }, { value: 'number', label: 'Number' },
        { value: 'date', label: 'Date' }, { value: 'url', label: 'URL' },
      ] },
      { key: 'max_retries', label: 'Max retries on invalid', type: 'number', min: 0, max: 5, step: 1 },
      { key: 'timeout_seconds', label: 'Timeout (seconds)', type: 'number', min: 30, step: 60,
        help: 'How long to wait for a reply before firing the "timeout" branch.' },
      { key: 'retry_message', label: 'Retry message', type: 'textarea', rows: 2, maxLength: 1024,
        help: 'Sent when the reply doesn\'t match the expected format.' },
    ],
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
    configSchema: [
      { key: 'prompt', label: 'Question', type: 'textarea', rows: 2, maxLength: 1024 },
      { key: 'save_to', label: 'Save address to', type: 'text',
        placeholder: 'contact.custom.address',
        help: 'Parsed street / city / postal are written under this key.' },
      { key: 'timeout_seconds', label: 'Timeout (seconds)', type: 'number', min: 30, step: 60 },
    ],
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
    configSchema: [
      { key: 'prompt', label: 'Question', type: 'textarea', rows: 2, maxLength: 1024 },
      { key: 'save_to', label: 'Save location to', type: 'text',
        placeholder: 'contact.custom.location',
        help: '{lat, lng} object is written under this key.' },
      { key: 'max_retries', label: 'Max retries on invalid', type: 'number', min: 0, max: 5, step: 1 },
      { key: 'timeout_seconds', label: 'Timeout (seconds)', type: 'number', min: 30, step: 60 },
    ],
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
    configSchema: [
      { key: 'prompt', label: 'Question', type: 'textarea', rows: 2, maxLength: 1024 },
      { key: 'save_to', label: 'Save file ID to', type: 'text',
        placeholder: 'contact.custom.uploaded_file_id' },
      { key: 'allowed_types', label: 'Allowed types', type: 'string_list',
        placeholder: 'image / video / document / audio, press Enter',
        help: 'Any inbound media type not in this list fires the "invalid" branch.' },
      { key: 'max_size_bytes', label: 'Max size (bytes)', type: 'number', min: 1024, step: 1024,
        help: 'Files above this size fire "invalid". Default 10 MiB (10485760).' },
      { key: 'max_retries', label: 'Max retries on invalid', type: 'number', min: 0, max: 5, step: 1 },
      { key: 'timeout_seconds', label: 'Timeout (seconds)', type: 'number', min: 30, step: 60 },
    ],
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
    configSchema: [
      { key: 'condition.left.path', label: 'Left side (path)', type: 'text',
        placeholder: 'answers.email',
        help: 'Read a value from: answers.<key>, contact.<field>, lead.<field>, run.<field>.' },
      { key: 'condition.op', label: 'Operator', type: 'select', options: [
        { value: 'equals', label: 'equals' },
        { value: 'not_equals', label: 'not equals' },
        { value: 'contains', label: 'contains' },
        { value: 'not_contains', label: 'does not contain' },
        { value: 'greater_than', label: 'greater than' },
        { value: 'less_than', label: 'less than' },
        { value: 'exists', label: 'exists' },
        { value: 'not_exists', label: 'does not exist' },
      ] },
      { key: 'condition.right.value', label: 'Right side (value)', type: 'text',
        placeholder: 'A literal to compare against',
        help: 'Ignored for "exists" / "does not exist". For lists use JSON: ["a", "b"].' },
    ],
  },
  {
    type: 'delay', label: 'Delay', icon: 'clock',
    category: 'action', paletteTab: 'actions', outputs: 'single',
    hint: 'Pause for N seconds / minutes / hours / days.',
    defaultConfig: { amount: 5, unit: 'minutes' },
    configSchema: [
      { key: 'amount', label: 'Wait for', type: 'number', min: 1, step: 1 },
      { key: 'unit', label: 'Unit', type: 'select', options: [
        { value: 'seconds', label: 'Seconds' }, { value: 'minutes', label: 'Minutes' },
        { value: 'hours', label: 'Hours' }, { value: 'days', label: 'Days' },
      ] },
    ],
  },
  {
    type: 'add_tag', label: 'Add Tag', icon: 'tag',
    category: 'action', paletteTab: 'actions', outputs: 'single',
    hint: 'Add or remove tags on the contact.',
    defaultConfig: { entity: 'contact', operation: 'add', tags: [] },
    configSchema: [
      { key: 'entity', label: 'Entity', type: 'select', options: [
        { value: 'contact', label: 'Contact' }, { value: 'lead', label: 'Lead' },
      ] },
      { key: 'operation', label: 'Operation', type: 'select', options: [
        { value: 'add', label: 'Add tags' }, { value: 'remove', label: 'Remove tags' },
      ] },
      { key: 'tags', label: 'Tags', type: 'string_list',
        placeholder: 'Type a tag, press Enter' },
    ],
  },
  {
    type: 'set_custom_field', label: 'Set Custom Field', icon: 'pencil',
    category: 'action', paletteTab: 'actions', outputs: 'single',
    hint: 'Write a static or templated value to a field.',
    defaultConfig: { save_to: 'contact.custom.', value: '' },
    configSchema: [
      { key: 'save_to', label: 'Save to field', type: 'text',
        placeholder: 'contact.custom.lead_score',
        help: 'Format: contact.<field>, lead.<field>, or contact.custom.<key>.' },
      { key: 'value', label: 'Value', type: 'textarea', rows: 2,
        placeholder: 'A literal value or {{template.expression}}',
        help: 'Static text or a Jinja-style template referencing answers / contact / lead.' },
    ],
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
    configSchema: [
      { key: 'method', label: 'Method', type: 'select', options: [
        { value: 'GET', label: 'GET' }, { value: 'POST', label: 'POST' },
        { value: 'PUT', label: 'PUT' }, { value: 'PATCH', label: 'PATCH' },
        { value: 'DELETE', label: 'DELETE' },
      ] },
      { key: 'url', label: 'URL', type: 'text', placeholder: 'https://api.example.com/webhook',
        help: 'HTTPS only. DNS + IP resolved server-side and blocked from private ranges (SSRF-safe).' },
      { key: 'headers', label: 'Headers', type: 'json',
        help: 'Object of { "Header-Name": "value" }. {{expressions}} allowed.' },
      { key: 'body_template', label: 'Request body', type: 'json',
        help: 'JSON body (any shape) — or null for GET / no body. {{expressions}} allowed.' },
      { key: 'timeout_seconds', label: 'Timeout (seconds)', type: 'number', min: 1, max: 30, step: 1 },
      { key: 'capture', label: 'Capture into answers', type: 'json',
        help: 'Object mapping answers keys to JSONPath ($.foo.bar) into the response body.' },
    ],
  },

  // --- Actions tab · CRM extras (4) ---
  {
    type: 'end_bot', label: 'End Bot', icon: 'check-circle-2',
    category: 'crm', paletteTab: 'actions', outputs: 'single',
    hint: 'Cleanly end the flow + optionally mute the bot for N hours.',
    defaultConfig: {
      final_bot_message: "Thanks, we'll be in touch shortly.",
      mute_hours: 0,
    },
    configSchema: [
      { key: 'final_bot_message', label: 'Final message (optional)', type: 'textarea',
        rows: 2, maxLength: 1024,
        placeholder: "Thanks, we'll be in touch shortly.",
        help: 'Leave empty to end silently.' },
      { key: 'mute_hours', label: 'Mute bot for (hours)', type: 'number',
        min: 0, max: 720,
        help: 'Prevents the trigger from firing again on this conversation for N hours. 0 = no mute. Max 720 (30 days).' },
    ],
  },
  {
    type: 'handoff_to_human', label: 'Handoff to Human', icon: 'bot',
    category: 'crm', paletteTab: 'actions', outputs: 'single',
    hint: 'Assign the conversation to a teammate + end the bot run.',
    defaultConfig: {
      assign_mode: 'specific', user_id: null,
      final_bot_message: 'A team member will jump in shortly.',
    },
    configSchema: [
      { key: 'assign_mode', label: 'Assign to', type: 'select', options: [
        { value: 'specific', label: 'Specific teammate' },
        { value: 'round_robin', label: 'Round-robin (any available)' },
        { value: 'contact_owner', label: 'Contact owner' },
      ] },
      { key: 'user_id', label: 'Teammate user ID', type: 'text',
        placeholder: 'UUID (leave empty for round-robin / owner modes)',
        help: 'Required only when Assign to = Specific teammate.' },
      { key: 'final_bot_message', label: 'Final bot message', type: 'textarea', rows: 2,
        maxLength: 1024,
        help: 'Sent to the customer just before the run ends and the human takes over.' },
    ],
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
    configSchema: [
      { key: 'source', label: 'Lead source', type: 'text',
        placeholder: 'chatbot',
        help: 'Free-text; shows in reporting. Common: chatbot, website, whatsapp.' },
      { key: 'pipeline_stage', label: 'Pipeline stage', type: 'text',
        placeholder: 'stage-id or blank for org default',
        help: 'Pipeline stage ID from /user/settings → Pipelines. Blank = default entry stage.' },
      { key: 'budget_from', label: 'Budget from (answers path)', type: 'text',
        placeholder: 'answers.budget',
        help: 'Read budget from a prior Ask Question answer, or a contact.custom.<key>.' },
      { key: 'expected_close_date_from', label: 'Expected close date from', type: 'text',
        placeholder: 'answers.close_date' },
      { key: 'custom_field_map', label: 'Custom field map', type: 'json',
        help: 'Object mapping lead custom-field keys to answers/contact paths or literals.' },
    ],
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
    configSchema: [
      { key: 'title_template', label: 'Title', type: 'textarea', rows: 2, maxLength: 200,
        placeholder: 'Bot appointment for {{contact.full_name}}',
        help: '{{expressions}} allowed — contact / answers / lead paths.' },
      { key: 'duration_minutes', label: 'Duration (minutes)', type: 'number', min: 5, max: 480, step: 5 },
      { key: 'scheduled_at_from', label: 'Slot from (answers path)', type: 'text',
        placeholder: 'answers.slot',
        help: 'Path to an ISO-8601 timestamp captured earlier in the flow.' },
      { key: 'assigned_to_user_id', label: 'Assigned to (user ID)', type: 'text',
        placeholder: 'Teammate UUID',
        help: 'Whose calendar to check + book. Blank = contact owner.' },
    ],
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
    configSchema: [
      { key: 'title', label: 'Task title', type: 'text', maxLength: 200,
        placeholder: 'Follow up with {{contact.full_name}}' },
      { key: 'assignee_mode', label: 'Assign to', type: 'select', options: [
        { value: 'contact_owner', label: 'Contact owner' },
        { value: 'lead_owner', label: 'Lead owner' },
        { value: 'specific', label: 'Specific teammate' },
        { value: 'bot_creator', label: 'Bot creator' },
      ] },
      { key: 'assignee_user_id', label: 'Teammate user ID', type: 'text',
        placeholder: 'UUID (required when Assign to = Specific teammate)' },
      { key: 'due_in_hours', label: 'Due in (hours)', type: 'number', min: 1, max: 720, step: 1 },
      { key: 'priority', label: 'Priority', type: 'select', options: [
        { value: 'low', label: 'Low' }, { value: 'medium', label: 'Medium' },
        { value: 'high', label: 'High' }, { value: 'urgent', label: 'Urgent' },
      ] },
    ],
  },

  // --- Actions tab · Flow + AI (3) ---
  {
    type: 'connect_flow', label: 'Connect Flow', icon: 'git-branch',
    category: 'action', paletteTab: 'actions', outputs: 'labeled',
    labels: ['error'],
    hint: 'Chain into another bot with answers passed through.',
    defaultConfig: { target_bot_id: '' },
    configSchema: [
      { key: 'target_bot_id', label: 'Target bot ID', type: 'text',
        placeholder: 'UUID of another bot in this org',
        help: 'Chain another bot. Max chain depth = 5 (guards infinite loops).' },
    ],
  },
  {
    type: 'single_ai_message', label: 'AI Message', icon: 'bot',
    category: 'ai', paletteTab: 'actions', outputs: 'labeled',
    labels: ['sent', 'error'],
    hint: 'One AI-generated reply. Bot advances to the next node afterwards — connect to End Bot if you want the bot to stop here.',
    defaultConfig: {
      system_prompt: 'You are a helpful assistant.',
      user_prompt_template: '{{run.last_inbound_text}}',
      max_tokens: 400, temperature: 0.4, save_reply_to: 'answers.ai_reply',
    },
    configSchema: [
      { key: 'system_prompt', label: 'System prompt', type: 'textarea', rows: 3, maxLength: 4000,
        placeholder: 'You are a helpful assistant.' },
      { key: 'user_prompt_template', label: 'User prompt', type: 'textarea', rows: 3, maxLength: 4000,
        placeholder: '{{run.last_inbound_text}}',
        help: 'Rendered with {{expressions}} before sending to the model.' },
      { key: 'max_tokens', label: 'Max tokens', type: 'number', min: 32, max: 4000, step: 32 },
      { key: 'temperature', label: 'Temperature', type: 'number', min: 0, max: 2, step: 0.1,
        help: '0 = deterministic, 1 = creative, 2 = wild.' },
      { key: 'save_reply_to', label: 'Save reply to', type: 'text',
        placeholder: 'answers.ai_reply',
        help: 'Path to save the model output — use in later Ask Question / Send Message nodes.' },
    ],
  },
  {
    type: 'assign_ai_assistant', label: 'AI Assistant', icon: 'bot',
    category: 'ai', paletteTab: 'actions', outputs: 'labeled',
    labels: ['handed_off', 'error'],
    hint: 'Hand the conversation to an AI Assistant for up to N turns.',
    defaultConfig: {
      assistant_id: '',
      max_turns: 8,
    },
    configSchema: [
      { key: 'assistant_id', label: 'Assistant ID', type: 'text',
        placeholder: 'Leave blank for the org\'s first active assistant',
        help: 'UUID of the AI Assistant to use (from /user/ai-assistants). Leave blank to auto-pick the org\'s first active assistant.' },
      { key: 'max_turns', label: 'Max turns before handoff', type: 'number', min: 1, max: 50, step: 1,
        help: 'AI answers up to this many customer messages, then the flow advances via the "handed_off" port.' },
    ],
  },
] as const;

export function getNodeType(type: string): NodeTypeMeta | undefined {
  return NODE_TYPES.find((n) => n.type === type);
}

export function nodesByTab(tab: PaletteTab): NodeTypeMeta[] {
  return NODE_TYPES.filter((n) => n.paletteTab === tab);
}
