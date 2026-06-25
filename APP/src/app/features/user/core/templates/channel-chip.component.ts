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
    classes: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  },
  email: {
    label: 'Email',
    icon: 'mail',
    classes: 'bg-blue-50 text-blue-700 ring-blue-200',
  },
  sms: {
    label: 'SMS',
    icon: 'phone',
    classes: 'bg-violet-50 text-violet-700 ring-violet-200',
  },
  facebook: {
    label: 'Messenger',
    icon: 'message-circle',
    classes: 'bg-sky-50 text-sky-700 ring-sky-200',
  },
  instagram: {
    label: 'Instagram',
    icon: 'message-circle',
    classes: 'bg-pink-50 text-pink-700 ring-pink-200',
  },
  web: {
    label: 'Push',
    icon: 'bell',
    classes: 'bg-amber-50 text-amber-700 ring-amber-200',
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
    return DESCRIPTORS[this.channel()] ?? {
      label: this.channel(),
      icon: 'tag',
      classes: 'bg-zinc-100 text-zinc-700 ring-zinc-200',
    };
  });
}
