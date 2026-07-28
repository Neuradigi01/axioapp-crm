/**
 * Typed registry of every workflow node type the canvas knows about.
 *
 * One row per type. The canvas + palette + state service all read from
 * this single source of truth — adding a new node type later means
 * extending this array, not touching the rendering code.
 *
 * Port topology is encoded as `inputPorts` (always 0 for trigger, 1 for
 * everything else) and `outputs` (the labelled list — empty for terminal
 * nodes, a single anonymous edge for sequential actions, branched
 * labels for if/else / switch / ab_split / wait_for_event).
 *
 * Categories map to the palette's section headers. Icons reference
 * Lucide names registered in `app.config.ts` — Step 13 already pulls
 * `Workflow`, `Mail`, `Send`, `Bell`, `Clock`, `Filter`, `Webhook`,
 * etc., so adding a new icon here requires registering it there too.
 *
 * Backend parity: every type listed here MUST be registered in
 * `core/workflows/actions/{send,record,routing,tag_lifecycle,
 * flow_control}.py` — the engine's `resolve_action` raises
 * `ActionNotRegistered` when a workflow references an unknown type.
 * The `trigger` type is special-cased and shares the single registered
 * `trigger` handler from `core/workflows/actions/trigger.py`.
 */
export type WorkflowNodeCategory =
  | 'trigger'
  | 'send'
  | 'record'
  | 'routing'
  | 'tag_lifecycle'
  | 'flow_control';

export interface NodeOutputPort {
  /** Edge label the engine matches when picking the next node. `null`
   *  means a single unlabelled edge (sequential action default). */
  label: string | null;
  /** Display name in the palette + canvas. */
  display: string;
}

export interface WorkflowNodeType {
  /** Canonical type string matching `core/workflows/actions` registry. */
  type: string;
  /** Section header in the palette. */
  category: WorkflowNodeCategory;
  /** Operator-facing label. */
  label: string;
  /** One-line description shown on the palette item hover. */
  description: string;
  /** Lucide icon name. */
  icon: string;
  /** Tailwind background-color class for the node body. */
  colorClass: string;
  /** 0 for trigger nodes; 1 for everything else. */
  inputPorts: 0 | 1;
  /** Ordered output port list. Empty for terminal-only nodes. */
  outputs: NodeOutputPort[];
}

// --- Triggers ----------------------------------------------------------
//
// One node type — `trigger`. Operator picks the specific event_type via
// the config drawer (Step 15) from the backend's event_catalog. The
// node has zero input ports (entry into the workflow) and a single
// unlabelled output.

const TRIGGER_NODE: WorkflowNodeType = {
  type: 'trigger',
  category: 'trigger',
  label: 'Trigger',
  description: 'Workflow entry point — fires on the chosen event.',
  icon: 'Zap',
  colorClass: 'bg-amber-50 border-amber-300',
  inputPorts: 0,
  outputs: [{ label: null, display: 'out' }],
};

// --- Send actions (7) ---------------------------------------------------

const SEND_NODES: WorkflowNodeType[] = [
  {
    type: 'send.email',
    category: 'send',
    label: 'Send email',
    description: 'Send a templated email through the org provider.',
    icon: 'Mail',
    colorClass: 'bg-sky-50 border-sky-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'send.whatsapp',
    category: 'send',
    label: 'Send WhatsApp',
    description: 'Send a templated WhatsApp via the active integration.',
    icon: 'MessageCircle',
    colorClass: 'bg-emerald-50 border-emerald-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'send.sms',
    category: 'send',
    label: 'Send SMS',
    description: 'Send a templated SMS via the org SMS provider.',
    icon: 'MessageSquare',
    colorClass: 'bg-emerald-50 border-emerald-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'send.facebook',
    category: 'send',
    label: 'Send Facebook message',
    description: 'Send a Messenger DM via the connected Page.',
    icon: 'Facebook',
    colorClass: 'bg-blue-50 border-blue-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'send.instagram',
    category: 'send',
    label: 'Send Instagram DM',
    description: 'Send a direct message via the connected IG account.',
    icon: 'Instagram',
    colorClass: 'bg-pink-50 border-pink-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'send.push',
    category: 'send',
    label: 'Send push notification',
    description: 'Send a push notification to the contact’s devices.',
    icon: 'BellRing',
    colorClass: 'bg-sky-50 border-sky-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'send.slack',
    category: 'send',
    label: 'Send Slack message',
    description: 'Post a message to a Slack channel via incoming webhook.',
    icon: 'Slack',
    colorClass: 'bg-violet-50 border-violet-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
];

// --- Record actions (8) -------------------------------------------------

const RECORD_NODES: WorkflowNodeType[] = [
  {
    type: 'record.update_contact',
    category: 'record',
    label: 'Update contact field',
    description: 'Set / clear a field on the contact (incl. custom_data).',
    icon: 'UserPen',
    colorClass: 'bg-surface-2 border-subtle',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'record.update_lead',
    category: 'record',
    label: 'Update lead field',
    description: 'Set / clear a field on the lead (incl. pipeline_stage).',
    icon: 'PenSquare',
    colorClass: 'bg-surface-2 border-subtle',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'record.update_appointment',
    category: 'record',
    label: 'Update appointment field',
    description: 'Patch fields on the appointment that triggered the run.',
    icon: 'CalendarCog',
    colorClass: 'bg-surface-2 border-subtle',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'record.create_task',
    category: 'record',
    label: 'Create task',
    description: 'Schedule a follow-up task for the assigned rep.',
    icon: 'ListTodo',
    colorClass: 'bg-amber-50 border-amber-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'record.create_note',
    category: 'record',
    label: 'Create note',
    description: 'Log a customer-visible note on the contact / lead.',
    icon: 'NotebookPen',
    colorClass: 'bg-amber-50 border-amber-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'record.create_appointment',
    category: 'record',
    label: 'Create appointment',
    description: 'Book an appointment on the assigned rep’s calendar.',
    icon: 'CalendarPlus',
    colorClass: 'bg-amber-50 border-amber-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'record.create_quote',
    category: 'record',
    label: 'Create quote',
    description: 'Generate a quote document and email it to the contact.',
    icon: 'Receipt',
    colorClass: 'bg-amber-50 border-amber-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'record.create_invoice',
    category: 'record',
    label: 'Create invoice',
    description: 'Issue an invoice tied to the contact / lead.',
    icon: 'FileText',
    colorClass: 'bg-amber-50 border-amber-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
];

// --- Routing actions (5) ------------------------------------------------

const ROUTING_NODES: WorkflowNodeType[] = [
  {
    type: 'routing.round_robin',
    category: 'routing',
    label: 'Route — round robin',
    description: 'Assign to the next rep in rotation.',
    icon: 'Shuffle',
    colorClass: 'bg-indigo-50 border-indigo-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'routing.least_loaded',
    category: 'routing',
    label: 'Route — least loaded',
    description: 'Assign to the rep with the fewest open records.',
    icon: 'ChartNoAxesColumn',
    colorClass: 'bg-indigo-50 border-indigo-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'routing.territory',
    category: 'routing',
    label: 'Route — by territory',
    description: 'Assign based on the contact’s region / pincode mapping.',
    icon: 'MapPin',
    colorClass: 'bg-indigo-50 border-indigo-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'routing.skill',
    category: 'routing',
    label: 'Route — by skill',
    description: 'Assign to a rep whose skills match the lead criteria.',
    icon: 'Wrench',
    colorClass: 'bg-indigo-50 border-indigo-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'routing.specific_user',
    category: 'routing',
    label: 'Route — specific user',
    description: 'Assign to a fixed rep chosen on this node.',
    icon: 'UserCheck',
    colorClass: 'bg-indigo-50 border-indigo-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
];

// --- Tagging + lifecycle (13) -------------------------------------------

const TAG_LIFECYCLE_NODES: WorkflowNodeType[] = [
  {
    type: 'tag.add',
    category: 'tag_lifecycle',
    label: 'Add tag',
    description: 'Add a tag to the contact / lead.',
    icon: 'Tag',
    colorClass: 'bg-teal-50 border-teal-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'tag.remove',
    category: 'tag_lifecycle',
    label: 'Remove tag',
    description: 'Remove a tag from the contact / lead.',
    icon: 'Ban',
    colorClass: 'bg-teal-50 border-teal-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'list.add',
    category: 'tag_lifecycle',
    label: 'Add to list',
    description: 'Add the contact to a static contact group.',
    icon: 'ListPlus',
    colorClass: 'bg-teal-50 border-teal-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'list.remove',
    category: 'tag_lifecycle',
    label: 'Remove from list',
    description: 'Remove the contact from a static contact group.',
    icon: 'ListMinus',
    colorClass: 'bg-teal-50 border-teal-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'lifecycle.set_score',
    category: 'tag_lifecycle',
    label: 'Set lead score',
    description: 'Set the lead score to a literal value or delta.',
    icon: 'Gauge',
    colorClass: 'bg-teal-50 border-teal-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'lifecycle.mark_converted',
    category: 'tag_lifecycle',
    label: 'Mark converted',
    description: 'Flip the lead to status=converted with a reason.',
    icon: 'CheckCircle2',
    colorClass: 'bg-emerald-50 border-emerald-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'lifecycle.mark_unsubscribed',
    category: 'tag_lifecycle',
    label: 'Mark unsubscribed',
    description: 'Set the contact’s marketing opt-out flag.',
    icon: 'BellOff',
    colorClass: 'bg-rose-50 border-rose-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'lifecycle.block',
    category: 'tag_lifecycle',
    label: 'Block contact',
    description: 'Add the contact’s number / email to the org block list.',
    icon: 'Ban',
    colorClass: 'bg-rose-50 border-rose-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'lifecycle.archive',
    category: 'tag_lifecycle',
    label: 'Archive contact',
    description: 'Hide the contact from active lists / search.',
    icon: 'Archive',
    colorClass: 'bg-surface-2 border-subtle',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'lifecycle.enroll_workflow',
    category: 'tag_lifecycle',
    label: 'Enrol in workflow',
    description: 'Enrol the contact in another workflow.',
    icon: 'Workflow',
    colorClass: 'bg-amber-50 border-amber-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'lifecycle.enroll_sequence',
    category: 'tag_lifecycle',
    label: 'Enrol in sequence',
    description: 'Enrol the contact in an email drip sequence.',
    icon: 'Mails',
    colorClass: 'bg-amber-50 border-amber-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'lifecycle.remove_workflow',
    category: 'tag_lifecycle',
    label: 'Remove from workflow',
    description: 'Cancel any active run of the chosen workflow for this contact.',
    icon: 'XSquare',
    colorClass: 'bg-surface-2 border-subtle',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'lifecycle.remove_sequence',
    category: 'tag_lifecycle',
    label: 'Remove from sequence',
    description: 'Cancel the contact’s active drip-sequence enrolment.',
    icon: 'MailX',
    colorClass: 'bg-surface-2 border-subtle',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
];

// --- Flow control (8) ---------------------------------------------------

const FLOW_CONTROL_NODES: WorkflowNodeType[] = [
  {
    type: 'flow_control.wait',
    category: 'flow_control',
    label: 'Wait (delay)',
    description: 'Pause the run for a configurable duration.',
    icon: 'Clock',
    colorClass: 'bg-surface-2 border-subtle',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'branch.if',
    category: 'flow_control',
    label: 'If / else',
    description: 'Branch on a condition: yes or no.',
    icon: 'GitBranch',
    colorClass: 'bg-yellow-50 border-yellow-300',
    inputPorts: 1,
    outputs: [
      { label: 'yes', display: 'yes' },
      { label: 'no', display: 'no' },
    ],
  },
  {
    type: 'branch.switch',
    category: 'flow_control',
    label: 'Switch',
    description: 'Branch into multiple cases based on a field’s value.',
    icon: 'GitFork',
    colorClass: 'bg-yellow-50 border-yellow-300',
    inputPorts: 1,
    // Switch cases are operator-defined (Step 15); the canvas
    // starts with a `default` output, the node-editor drawer adds
    // more case labels later.
    outputs: [{ label: 'default', display: 'default' }],
  },
  {
    type: 'flow_control.ab_split',
    category: 'flow_control',
    label: 'A/B split',
    description: 'Deterministically route runs into A or B branches.',
    icon: 'SplitSquareHorizontal',
    colorClass: 'bg-yellow-50 border-yellow-300',
    inputPorts: 1,
    outputs: [
      { label: 'a', display: 'A' },
      { label: 'b', display: 'B' },
    ],
  },
  {
    type: 'flow_control.goal',
    category: 'flow_control',
    label: 'Goal',
    description: 'Marker: when the run terminates here, outcome=goal_reached.',
    icon: 'Target',
    colorClass: 'bg-emerald-50 border-emerald-300',
    inputPorts: 1,
    outputs: [],
  },
  {
    type: 'flow_control.wait_for_event',
    category: 'flow_control',
    label: 'Wait for event',
    description: 'Pause until a specific event fires, or time out.',
    icon: 'CircleDot',
    colorClass: 'bg-surface-2 border-subtle',
    inputPorts: 1,
    outputs: [
      { label: 'event_received', display: 'event' },
      { label: 'timeout', display: 'timeout' },
    ],
  },
  {
    type: 'flow_control.call_webhook',
    category: 'flow_control',
    label: 'Call webhook',
    description: 'POST a JSON payload to an external HTTPS URL.',
    icon: 'Webhook',
    colorClass: 'bg-violet-50 border-violet-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
  {
    type: 'flow_control.notify_user',
    category: 'flow_control',
    label: 'Notify user',
    description: 'Send an in-app notification to the workflow owner / lead owner.',
    icon: 'BellPlus',
    colorClass: 'bg-violet-50 border-violet-300',
    inputPorts: 1,
    outputs: [{ label: null, display: 'out' }],
  },
];

// --- Internal-note flow control variant ---------------------------------
//
// Step 11 ships `flow_control.log_internal_note` as a 14th tag-lifecycle
// action. Kept in flow_control here to match the spec's "13 tagging +
// lifecycle, 8 flow control" split (13 + 8 = 21 + 5 + 8 + 1 = ... 7 =
// 42 nodes total).
const INTERNAL_NOTE_NODE: WorkflowNodeType = {
  type: 'flow_control.log_internal_note',
  category: 'tag_lifecycle',
  label: 'Log internal note',
  description: 'Write a private note on the timeline (hidden from customer-shared views).',
  icon: 'PenLine',
  colorClass: 'bg-surface-2 border-subtle',
  inputPorts: 1,
  outputs: [{ label: null, display: 'out' }],
};

// --- Public registry ----------------------------------------------------

export const NODE_TYPES: readonly WorkflowNodeType[] = [
  TRIGGER_NODE,
  ...SEND_NODES,
  ...RECORD_NODES,
  ...ROUTING_NODES,
  ...TAG_LIFECYCLE_NODES,
  INTERNAL_NOTE_NODE,
  ...FLOW_CONTROL_NODES,
];

export const NODE_TYPES_BY_KEY: ReadonlyMap<string, WorkflowNodeType> = new Map(
  NODE_TYPES.map((n) => [n.type, n]),
);

export function getNodeType(type: string): WorkflowNodeType | undefined {
  return NODE_TYPES_BY_KEY.get(type);
}

export const PALETTE_SECTIONS: ReadonlyArray<{
  key: WorkflowNodeCategory;
  label: string;
}> = [
  { key: 'trigger', label: 'Triggers' },
  { key: 'send', label: 'Send actions' },
  { key: 'record', label: 'Record actions' },
  { key: 'routing', label: 'Routing' },
  { key: 'tag_lifecycle', label: 'Tagging + lifecycle' },
  { key: 'flow_control', label: 'Flow control' },
];
