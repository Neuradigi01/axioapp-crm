/**
 * Per-node-editor contract.
 *
 * Every editor component takes a single `[node]` input (the live
 * CanvasNode the user clicked) and emits two outputs:
 *
 *   `(configChange)` — a partial config patch the parent merges into
 *                      `node.config` via `CanvasStateService.updateNodeConfig`.
 *   `(validityChange)` — `true` when every required field is present /
 *                        valid; `false` when the node should show the red
 *                        validation dot. The parent stamps
 *                        `node.config.__valid` so the node card reflects.
 *
 * The dispatcher (`node-editor.component`) maps `node.type` to one of
 * 27 sub-editors. Each sub-editor is purely presentational — no DB,
 * no HTTP except read-side picker components.
 */

import { CanvasNode } from '../canvas-state.service';

/** Standard editor IO surface. Implementing components don't need to
 *  formally extend this — it documents the shape we wire by convention. */
export interface NodeEditorContract {
  node: CanvasNode;
  configChange: { emit(patch: Record<string, unknown>): void };
  validityChange: { emit(valid: boolean): void };
}

// --- Conditions AST -----------------------------------------------------

/** Operators the conditions-builder UI exposes. Backend (Step 6) maps
 *  each to its evaluation function. */
export type ConditionOp =
  | 'eq'
  | 'neq'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'in'
  | 'not_in'
  | 'contains'
  | 'starts_with'
  | 'ends_with'
  | 'is_empty'
  | 'is_not_empty'
  | 'changed_to';

export interface ConditionLeaf {
  kind: 'leaf';
  path: string;
  op: ConditionOp;
  value: unknown;
}

export interface ConditionAnd {
  kind: 'and';
  children: ConditionNode[];
}

export interface ConditionOr {
  kind: 'or';
  children: ConditionNode[];
}

export interface ConditionNot {
  kind: 'not';
  child: ConditionNode;
}

export type ConditionNode = ConditionLeaf | ConditionAnd | ConditionOr | ConditionNot;

export const CONDITION_OPS: Array<{ value: ConditionOp; label: string }> = [
  { value: 'eq', label: 'equals' },
  { value: 'neq', label: 'not equals' },
  { value: 'gt', label: 'greater than' },
  { value: 'gte', label: 'greater or equal' },
  { value: 'lt', label: 'less than' },
  { value: 'lte', label: 'less or equal' },
  { value: 'in', label: 'in (comma-separated)' },
  { value: 'not_in', label: 'not in (comma-separated)' },
  { value: 'contains', label: 'contains' },
  { value: 'starts_with', label: 'starts with' },
  { value: 'ends_with', label: 'ends with' },
  { value: 'is_empty', label: 'is empty' },
  { value: 'is_not_empty', label: 'is not empty' },
  { value: 'changed_to', label: 'changed to' },
];

export function emptyAndGroup(): ConditionAnd {
  return { kind: 'and', children: [] };
}

export function emptyLeaf(): ConditionLeaf {
  return { kind: 'leaf', path: '', op: 'eq', value: '' };
}

// --- Variable contexts --------------------------------------------------

/** Per-event_type variable schema. Surfaced to the variable-picker so
 *  the operator can browse what's available given the current trigger.
 *  Backend's `event_catalog.VARIABLES_BY_EVENT` is the authoritative
 *  source; this map is a sane fallback for offline / pre-API-call
 *  rendering, and a single shared source for the picker UI. */
export interface VariablePath {
  /** Dotted path inserted into the template — e.g. `lead.score`. */
  path: string;
  /** Operator-facing label. */
  label: string;
  /** One-line description shown on hover. */
  description: string;
}

export interface VariableGroup {
  /** Section header in the picker — e.g. "Lead", "Contact". */
  label: string;
  paths: VariablePath[];
}

export const ALWAYS_AVAILABLE: VariableGroup = {
  label: 'Always available',
  paths: [
    { path: 'now', label: 'now', description: 'Current timestamp.' },
    { path: 'org.name', label: 'org.name', description: 'Workspace display name.' },
    {
      path: 'actor.email',
      label: 'actor.email',
      description: 'Email of the user who triggered the run.',
    },
  ],
};

const CONTACT_GROUP: VariableGroup = {
  label: 'Contact',
  paths: [
    { path: 'contact.full_name', label: 'contact.full_name', description: 'Contact full name.' },
    { path: 'contact.email', label: 'contact.email', description: 'Contact email.' },
    { path: 'contact.phone', label: 'contact.phone', description: 'Contact phone.' },
    { path: 'contact.source', label: 'contact.source', description: 'Acquisition source.' },
    {
      path: 'contact.assigned_to',
      label: 'contact.assigned_to',
      description: 'Rep assigned to this contact.',
    },
  ],
};

const LEAD_GROUP: VariableGroup = {
  label: 'Lead',
  paths: [
    { path: 'lead.id', label: 'lead.id', description: 'Lead UUID.' },
    { path: 'lead.status', label: 'lead.status', description: 'Lifecycle status.' },
    {
      path: 'lead.pipeline_stage',
      label: 'lead.pipeline_stage',
      description: 'Current pipeline stage key.',
    },
    { path: 'lead.budget', label: 'lead.budget', description: 'Quoted budget value.' },
    { path: 'lead.lead_score', label: 'lead.lead_score', description: 'Computed lead score.' },
    {
      path: 'lead.assigned_to',
      label: 'lead.assigned_to',
      description: 'Rep assigned to this lead.',
    },
    {
      path: 'lead.expected_close_date',
      label: 'lead.expected_close_date',
      description: 'Operator-set close date.',
    },
  ],
};

const APPOINTMENT_GROUP: VariableGroup = {
  label: 'Appointment',
  paths: [
    { path: 'appointment.id', label: 'appointment.id', description: 'Appointment UUID.' },
    { path: 'appointment.title', label: 'appointment.title', description: 'Operator-set title.' },
    {
      path: 'appointment.scheduled_at',
      label: 'appointment.scheduled_at',
      description: 'Scheduled timestamp.',
    },
    {
      path: 'appointment.status',
      label: 'appointment.status',
      description: 'scheduled / completed / no_show / canceled.',
    },
  ],
};

const TASK_GROUP: VariableGroup = {
  label: 'Task',
  paths: [
    { path: 'task.id', label: 'task.id', description: 'Task UUID.' },
    { path: 'task.title', label: 'task.title', description: 'Task title.' },
    { path: 'task.due_at', label: 'task.due_at', description: 'Task due timestamp.' },
    { path: 'task.status', label: 'task.status', description: 'open / done.' },
  ],
};

const QUOTE_GROUP: VariableGroup = {
  label: 'Quote',
  paths: [
    { path: 'quote.id', label: 'quote.id', description: 'Quote UUID.' },
    { path: 'quote.total', label: 'quote.total', description: 'Quote total in org currency.' },
    { path: 'quote.expires_at', label: 'quote.expires_at', description: 'Quote expiry timestamp.' },
  ],
};

const INVOICE_GROUP: VariableGroup = {
  label: 'Invoice',
  paths: [
    { path: 'invoice.id', label: 'invoice.id', description: 'Invoice UUID.' },
    { path: 'invoice.total', label: 'invoice.total', description: 'Invoice total.' },
    { path: 'invoice.due_at', label: 'invoice.due_at', description: 'Due date.' },
  ],
};

const CONVERSATION_GROUP: VariableGroup = {
  label: 'Conversation',
  paths: [
    {
      path: 'conversation.channel',
      label: 'conversation.channel',
      description: 'email / whatsapp / sms / etc.',
    },
    {
      path: 'conversation.last_message_text',
      label: 'conversation.last_message_text',
      description: 'Body of the latest inbound message.',
    },
  ],
};

/** Map from event_type prefix → groups available in that run context.
 *  The picker collapses to `[ALWAYS_AVAILABLE]` when no trigger is set
 *  or the type isn't recognised. */
export const VARIABLE_GROUPS_BY_EVENT_PREFIX: Record<string, VariableGroup[]> = {
  'lead.': [LEAD_GROUP, CONTACT_GROUP, ALWAYS_AVAILABLE],
  'contact.': [CONTACT_GROUP, ALWAYS_AVAILABLE],
  'appointment.': [APPOINTMENT_GROUP, CONTACT_GROUP, LEAD_GROUP, ALWAYS_AVAILABLE],
  'task.': [TASK_GROUP, CONTACT_GROUP, LEAD_GROUP, ALWAYS_AVAILABLE],
  'quote.': [QUOTE_GROUP, CONTACT_GROUP, LEAD_GROUP, ALWAYS_AVAILABLE],
  'invoice.': [INVOICE_GROUP, CONTACT_GROUP, ALWAYS_AVAILABLE],
  'email.': [CONVERSATION_GROUP, CONTACT_GROUP, ALWAYS_AVAILABLE],
  'whatsapp.': [CONVERSATION_GROUP, CONTACT_GROUP, ALWAYS_AVAILABLE],
  'sms.': [CONVERSATION_GROUP, CONTACT_GROUP, ALWAYS_AVAILABLE],
};

export function variableGroupsForEvent(eventType: string | null | undefined): VariableGroup[] {
  if (!eventType) return [ALWAYS_AVAILABLE];
  for (const prefix of Object.keys(VARIABLE_GROUPS_BY_EVENT_PREFIX)) {
    if (eventType.startsWith(prefix)) {
      return VARIABLE_GROUPS_BY_EVENT_PREFIX[prefix];
    }
  }
  return [ALWAYS_AVAILABLE];
}

// --- Event catalogue (operator-facing labels for the trigger picker) ----

export interface EventTypeOption {
  type: string;
  label: string;
  description: string;
  /** True if a contact can "expect" this event (used by the wait-for-
   *  event editor to filter the picker). */
  waitable: boolean;
}

export const EVENT_TYPES: readonly EventTypeOption[] = [
  // Lead lifecycle
  {
    type: 'lead.created',
    label: 'Lead created',
    description: 'A new lead row was inserted.',
    waitable: false,
  },
  {
    type: 'lead.updated',
    label: 'Lead updated',
    description: 'Any lead field changed.',
    waitable: false,
  },
  {
    type: 'lead.stage_changed',
    label: 'Lead stage changed',
    description: 'Pipeline stage moved.',
    waitable: false,
  },
  {
    type: 'lead.converted',
    label: 'Lead converted',
    description: 'Lead flipped to status=converted.',
    waitable: false,
  },
  {
    type: 'lead.lost',
    label: 'Lead lost',
    description: 'Lead flipped to status=lost.',
    waitable: false,
  },

  // Contact lifecycle
  {
    type: 'contact.created',
    label: 'Contact created',
    description: 'A new contact was added.',
    waitable: false,
  },
  {
    type: 'contact.updated',
    label: 'Contact updated',
    description: 'Any contact field changed.',
    waitable: false,
  },
  {
    type: 'contact.tag_added',
    label: 'Tag added to contact',
    description: 'A tag was applied.',
    waitable: false,
  },
  {
    type: 'contact.tag_removed',
    label: 'Tag removed from contact',
    description: 'A tag was removed.',
    waitable: false,
  },

  // Appointments / tasks
  {
    type: 'appointment.created',
    label: 'Appointment created',
    description: 'New appointment scheduled.',
    waitable: false,
  },
  {
    type: 'appointment.completed',
    label: 'Appointment completed',
    description: 'Rep marked it complete.',
    waitable: true,
  },
  {
    type: 'appointment.no_show',
    label: 'Appointment no-show',
    description: 'Rep marked it no-show.',
    waitable: true,
  },
  {
    type: 'task.completed',
    label: 'Task completed',
    description: 'Task moved to done.',
    waitable: true,
  },

  // Conversations
  {
    type: 'email.delivered',
    label: 'Email delivered',
    description: 'Email accepted by the recipient MTA.',
    waitable: true,
  },
  {
    type: 'email.opened',
    label: 'Email opened',
    description: 'Pixel beacon fired.',
    waitable: true,
  },
  {
    type: 'email.clicked',
    label: 'Email link clicked',
    description: 'Click tracker fired.',
    waitable: true,
  },
  {
    type: 'email.bounced',
    label: 'Email bounced',
    description: 'Hard / soft bounce from the MTA.',
    waitable: true,
  },
  {
    type: 'email.replied',
    label: 'Email replied',
    description: 'Contact replied to a sent email.',
    waitable: true,
  },
  {
    type: 'whatsapp.message_received',
    label: 'WhatsApp message received',
    description: 'Inbound WA message.',
    waitable: true,
  },
  {
    type: 'whatsapp.message_read',
    label: 'WhatsApp message read',
    description: 'Recipient opened the message.',
    waitable: true,
  },
  {
    type: 'sms.delivered',
    label: 'SMS delivered',
    description: 'Carrier confirmed delivery.',
    waitable: true,
  },
  {
    type: 'sms.replied',
    label: 'SMS replied',
    description: 'Contact replied to a sent SMS.',
    waitable: true,
  },

  // Billing
  {
    type: 'quote.sent',
    label: 'Quote sent',
    description: 'Quote emailed to the contact.',
    waitable: false,
  },
  {
    type: 'quote.viewed',
    label: 'Quote viewed',
    description: 'Contact opened the quote.',
    waitable: true,
  },
  {
    type: 'quote.accepted',
    label: 'Quote accepted',
    description: 'Contact accepted the quote.',
    waitable: true,
  },
  { type: 'invoice.sent', label: 'Invoice sent', description: 'Invoice issued.', waitable: false },
  { type: 'invoice.paid', label: 'Invoice paid', description: 'Payment received.', waitable: true },
];

export const WAITABLE_EVENT_TYPES = EVENT_TYPES.filter((e) => e.waitable);

// --- Recipient resolvers (used by send editors) -------------------------

export interface RecipientOption {
  value: string;
  label: string;
  description: string;
}

export const EMAIL_RECIPIENTS: readonly RecipientOption[] = [
  {
    value: 'contact.email',
    label: "Contact's email",
    description: 'Send to the contact tied to this run.',
  },
  {
    value: 'lead.owner',
    label: "Lead owner's email",
    description: 'Send to the rep assigned to the lead.',
  },
  {
    value: 'user.email',
    label: "Workflow owner's email",
    description: 'Send to the user who created the workflow.',
  },
  {
    value: 'custom',
    label: 'Custom path…',
    description: 'Provide a dotted path or literal email below.',
  },
];

export const PHONE_RECIPIENTS: readonly RecipientOption[] = [
  {
    value: 'contact.phone',
    label: "Contact's phone",
    description: 'Send to the contact tied to this run.',
  },
  {
    value: 'custom',
    label: 'Custom path…',
    description: 'Provide a dotted path or literal phone below.',
  },
];

export const SEND_CATEGORIES: readonly RecipientOption[] = [
  {
    value: 'marketing',
    label: 'Marketing',
    description: 'Subject to opt-in + quiet hours + frequency cap.',
  },
  {
    value: 'transactional',
    label: 'Transactional',
    description: 'Service / account messages — bypasses marketing gates.',
  },
  { value: 'service', label: 'Service', description: 'Customer support / notification.' },
];
