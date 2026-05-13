import { ChangeDetectionStrategy, Component } from '@angular/core';

interface Integration {
  id: string;
  name: string;
  description: string;
  status: 'connected' | 'not_configured' | 'planned';
  phase: string;
}

/**
 * Integrations tab — placeholders + status pills. The WhatsApp row
 * picks its status from a server-side health probe in Phase 5; for
 * now everything is read-only and the row text explains when the
 * real wiring lands.
 */
@Component({
  selector: 'app-settings-integrations-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  templateUrl: './integrations-tab.component.html',
})
export class IntegrationsTabComponent {
  protected readonly items: ReadonlyArray<Integration> = [
    {
      id: 'whatsapp',
      name: 'WhatsApp Business Cloud API',
      description:
        'Outbound + webhook intake. Set WHATSAPP_PHONE_ID, WHATSAPP_TOKEN, WHATSAPP_VERIFY_TOKEN and WHATSAPP_APP_SECRET in .env to go live.',
      status: 'not_configured',
      phase: 'Adapter shipped in 3.9',
    },
    {
      id: 'meta-marketplace',
      name: 'Meta Marketplace',
      description: 'List inventory on Facebook Marketplace.',
      status: 'planned',
      phase: 'Phase 5',
    },
    {
      id: 'instagram',
      name: 'Instagram DM',
      description: 'Inbound DMs land in the Conversations inbox.',
      status: 'planned',
      phase: 'Phase 5',
    },
    {
      id: 'razorpay',
      name: 'Razorpay payments',
      description: 'Collect deposits + final payments via UPI / cards.',
      status: 'planned',
      phase: 'Phase 5',
    },
  ];

  protected statusBadge(s: Integration['status']): {
    label: string;
    cls: string;
  } {
    switch (s) {
      case 'connected':
        return {
          label: 'Connected',
          cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
        };
      case 'not_configured':
        return {
          label: 'Not configured',
          cls: 'bg-amber-50 text-amber-700 ring-amber-200',
        };
      case 'planned':
        return {
          label: 'Planned',
          cls: 'bg-zinc-100 text-zinc-600 ring-zinc-200',
        };
    }
  }
}
