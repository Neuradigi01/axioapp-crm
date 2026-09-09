import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { ConfirmDialogService } from '../../shared/confirm-dialog/confirm-dialog.service';
import { CanvasNode, CanvasStateService } from './canvas-state.service';
import { getNodeType } from './node-type-registry';

import { AbSplitEditorComponent } from './editors/ab-split-editor.component';
import { BranchEditorComponent } from './editors/branch-editor.component';
import { CreateAppointmentEditorComponent } from './editors/create-appointment-editor.component';
import { CreateInvoiceEditorComponent } from './editors/create-invoice-editor.component';
import { CreateNoteEditorComponent } from './editors/create-note-editor.component';
import { CreateQuoteEditorComponent } from './editors/create-quote-editor.component';
import { CreateTaskEditorComponent } from './editors/create-task-editor.component';
import { EnrollEditorComponent } from './editors/enroll-editor.component';
import { GoalEditorComponent } from './editors/goal-editor.component';
import { LifecycleEditorComponent } from './editors/lifecycle-editor.component';
import { NotifyUserEditorComponent } from './editors/notify-user-editor.component';
import { RoutingEditorComponent } from './editors/routing-editor.component';
import { SendEmailEditorComponent } from './editors/send-email-editor.component';
import { SendFbEditorComponent } from './editors/send-fb-editor.component';
import { SendIgEditorComponent } from './editors/send-ig-editor.component';
import { SendPushEditorComponent } from './editors/send-push-editor.component';
import { SendSlackEditorComponent } from './editors/send-slack-editor.component';
import { SendSmsEditorComponent } from './editors/send-sms-editor.component';
import { SendWhatsAppEditorComponent } from './editors/send-whatsapp-editor.component';
import { SwitchEditorComponent } from './editors/switch-editor.component';
import { TaggingEditorComponent } from './editors/tagging-editor.component';
import { TriggerEditorComponent } from './editors/trigger-editor.component';
import { UpdateFieldEditorComponent } from './editors/update-field-editor.component';
import { WaitEditorComponent } from './editors/wait-editor.component';
import { WaitForEventEditorComponent } from './editors/wait-for-event-editor.component';
import { WebhookEditorComponent } from './editors/webhook-editor.component';

/**
 * Right-drawer body — switches on `node.type` and renders the
 * matching typed sub-editor. Header collects the node label, the
 * "Disconnect" / "Delete" actions; body delegates to one of 27 sub-
 * editors covering all 42 node types.
 *
 * The component is the single bridge between the per-editor child IO
 * (`configChange`, `validityChange`) and the canvas state service —
 * children stay pure. Config patches merge via
 * `state.updateNodeConfig`; validity stamps `__valid` on the node's
 * config so the SVG node card can render the red validation dot.
 */

@Component({
  selector: 'app-node-editor',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    LucideAngularModule,
    AbSplitEditorComponent,
    BranchEditorComponent,
    CreateAppointmentEditorComponent,
    CreateInvoiceEditorComponent,
    CreateNoteEditorComponent,
    CreateQuoteEditorComponent,
    CreateTaskEditorComponent,
    EnrollEditorComponent,
    GoalEditorComponent,
    LifecycleEditorComponent,
    NotifyUserEditorComponent,
    RoutingEditorComponent,
    SendEmailEditorComponent,
    SendFbEditorComponent,
    SendIgEditorComponent,
    SendPushEditorComponent,
    SendSlackEditorComponent,
    SendSmsEditorComponent,
    SendWhatsAppEditorComponent,
    SwitchEditorComponent,
    TaggingEditorComponent,
    TriggerEditorComponent,
    UpdateFieldEditorComponent,
    WaitEditorComponent,
    WaitForEventEditorComponent,
    WebhookEditorComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './node-editor.component.html',
})
export class NodeEditorComponent {
  readonly node = input.required<CanvasNode>();
  readonly close = output<void>();

  private readonly state = inject(CanvasStateService);
  private readonly confirmDialog = inject(ConfirmDialogService);

  readonly nodeType = computed(() => getNodeType(this.node().type));

  readonly displayLabel = computed<string>(() => {
    const cfg = this.node().config as Record<string, unknown> | undefined;
    return (cfg?.['label'] as string) ?? this.nodeType()?.label ?? this.node().type;
  });

  /** Returns the right editor key for the `@switch` dispatch. Groups
   *  related types (e.g. all `record.update_*` → 'update_field';
   *  `tag.*` + `list.*` + `lifecycle.set_score` → 'tagging';
   *  4 lifecycle marker types → 'lifecycle'; 4 enroll/remove types →
   *  'enroll') so the dispatcher stays compact. */
  readonly editorKey = computed<string>(() => {
    const t = this.node().type;
    if (t === 'trigger' || t.startsWith('trigger.')) return 'trigger';
    if (t === 'send.email') return 'send_email';
    if (t === 'send.whatsapp') return 'send_whatsapp';
    if (t === 'send.sms') return 'send_sms';
    if (t === 'send.facebook') return 'send_fb';
    if (t === 'send.instagram') return 'send_ig';
    if (t === 'send.push') return 'send_push';
    if (t === 'send.slack') return 'send_slack';
    if (t.startsWith('record.update_')) return 'update_field';
    if (t === 'record.create_task') return 'create_task';
    if (t === 'record.create_note' || t === 'flow_control.log_internal_note') {
      return 'create_note';
    }
    if (t === 'record.create_appointment') return 'create_appointment';
    if (t === 'record.create_quote') return 'create_quote';
    if (t === 'record.create_invoice') return 'create_invoice';
    if (t.startsWith('routing.')) return 'routing';
    if (
      t === 'tag.add' ||
      t === 'tag.remove' ||
      t === 'list.add' ||
      t === 'list.remove' ||
      t === 'lifecycle.set_score'
    ) {
      return 'tagging';
    }
    if (
      t === 'lifecycle.mark_converted' ||
      t === 'lifecycle.mark_unsubscribed' ||
      t === 'lifecycle.block' ||
      t === 'lifecycle.archive'
    ) {
      return 'lifecycle';
    }
    if (
      t === 'lifecycle.enroll_workflow' ||
      t === 'lifecycle.enroll_sequence' ||
      t === 'lifecycle.remove_workflow' ||
      t === 'lifecycle.remove_sequence'
    ) {
      return 'enroll';
    }
    if (t === 'flow_control.wait') return 'wait';
    if (t === 'branch.if') return 'branch';
    if (t === 'branch.switch') return 'switch';
    if (t === 'flow_control.ab_split') return 'ab_split';
    if (t === 'flow_control.goal') return 'goal';
    if (t === 'flow_control.wait_for_event') return 'wait_for_event';
    if (t === 'flow_control.call_webhook') return 'webhook';
    if (t === 'flow_control.notify_user') return 'notify_user';
    return 'unknown';
  });

  // --- header actions -------------------------------------------------

  onLabelChange(value: string): void {
    this.state.updateNodeConfig(this.node().id, { label: value });
  }

  onDuplicate(): void {
    this.state.duplicateNode(this.node().id);
  }

  onDisconnect(): void {
    const id = this.node().id;
    for (const e of this.state.edges()) {
      if (e.source === id || e.target === id) {
        this.state.deleteEdge(e.id);
      }
    }
  }

  async onDelete(): Promise<void> {
    const ok = await this.confirmDialog.ask({
      title: 'Delete this node?',
      body: 'The node and every edge attached to it will be removed. You can undo with Ctrl+Z.',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    this.state.deleteNode(this.node().id);
    this.close.emit();
  }

  // --- child IO bridge ------------------------------------------------

  onConfigChange(patch: Record<string, unknown>): void {
    this.state.updateNodeConfig(this.node().id, patch);
  }

  onValidityChange(valid: boolean): void {
    const current = this.node().config?.['__valid'];
    if (current === valid) return;
    this.state.updateNodeConfig(this.node().id, { __valid: valid });
  }
}
