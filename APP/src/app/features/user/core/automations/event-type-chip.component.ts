import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

/**
 * Event-type chip — small icon + human-readable label per
 * `event_type` string. Matches the channel-chip pattern from the
 * templates module so the automations list looks like a peer
 * surface.
 *
 * Icon palette intentionally narrow: every event picks one of the
 * four families (user / lead / sales / appointment / time) so the
 * list row reads at a glance.
 */
interface EventTypeDescriptor {
  label: string;
  icon: string;
  classes: string;
}

const PREFIX_DESCRIPTORS: Array<{
  prefix: string;
  descriptor: EventTypeDescriptor;
}> = [
  {
    prefix: 'user.',
    descriptor: {
      label: 'User',
      icon: 'user-plus',
      classes: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    },
  },
  {
    prefix: 'lead.',
    descriptor: {
      label: 'Lead',
      icon: 'target',
      classes: 'bg-amber-50 text-amber-700 ring-amber-200',
    },
  },
  {
    prefix: 'contact.',
    descriptor: {
      label: 'Contact',
      icon: 'users',
      classes: 'bg-blue-50 text-blue-700 ring-blue-200',
    },
  },
  {
    prefix: 'appointment.',
    descriptor: {
      label: 'Appointment',
      icon: 'calendar',
      classes: 'bg-violet-50 text-violet-700 ring-violet-200',
    },
  },
  {
    prefix: 'quote.',
    descriptor: {
      label: 'Quote',
      icon: 'receipt',
      classes: 'bg-cyan-50 text-cyan-700 ring-cyan-200',
    },
  },
  {
    prefix: 'invoice.',
    descriptor: {
      label: 'Invoice',
      icon: 'receipt',
      classes: 'bg-rose-50 text-rose-700 ring-rose-200',
    },
  },
  {
    prefix: 'time.',
    descriptor: {
      label: 'Time',
      icon: 'clock',
      classes: 'bg-surface-2 text-default border-subtle',
    },
  },
];

@Component({
  selector: 'app-event-type-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './event-type-chip.component.html',
})
export class EventTypeChipComponent {
  readonly eventType = input.required<string>();

  protected readonly descriptor = computed<EventTypeDescriptor & { event_type: string }>(() => {
    const et = this.eventType();
    for (const entry of PREFIX_DESCRIPTORS) {
      if (et.startsWith(entry.prefix)) {
        return { ...entry.descriptor, event_type: et };
      }
    }
    return {
      label: et,
      icon: 'zap',
      classes: 'bg-surface-2 text-default border-subtle',
      event_type: et,
    };
  });
}
