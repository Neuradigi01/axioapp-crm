import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import type { TemplateChannel } from './templates-api.service';

/**
 * Channel chip — a small (icon + label) pill rendering the template's
 * channel. Reused by the list table (Step 6) and the editor's channel
 * sub-form header (Step 7).
 *
 * Icons are the Lucide IDs already registered in `app.config.ts`; no
 * new icon imports needed.
 */
interface ChannelDescriptor {
  label: string;
  icon: string;
  classes: string;
}

const DESCRIPTORS: Record<TemplateChannel, ChannelDescriptor> = {
  whatsapp: {
    label: 'WhatsApp',
    icon: 'message-circle',
    classes: 'bg-emerald-500/10 text-emerald-700 ring-emerald-500/20',
  },
  email: {
    label: 'Email',
    icon: 'mail',
    classes: 'bg-blue-500/10 text-blue-700 ring-blue-500/20',
  },
  sms: {
    label: 'SMS',
    icon: 'phone',
    classes: 'bg-violet-500/10 text-violet-700 ring-violet-500/20',
  },
  facebook: {
    label: 'Messenger',
    icon: 'message-circle',
    classes: 'bg-sky-500/10 text-sky-700 ring-sky-500/20',
  },
  instagram: {
    label: 'Instagram',
    icon: 'message-circle',
    classes: 'bg-pink-500/10 text-pink-700 ring-pink-500/20',
  },
  push: {
    label: 'Push',
    icon: 'bell',
    classes: 'bg-amber-500/10 text-amber-700 ring-amber-500/20',
  },
};

@Component({
  selector: 'app-channel-chip',
  standalone: true,
  imports: [LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './channel-chip.component.html',
})
export class ChannelChipComponent {
  readonly channel = input.required<TemplateChannel>();

  protected readonly descriptor = computed<ChannelDescriptor>(() => {
    return (
      DESCRIPTORS[this.channel()] ?? {
        label: this.channel(),
        icon: 'tag',
        classes: 'bg-surface-2 text-default border-subtle',
      }
    );
  });
}
