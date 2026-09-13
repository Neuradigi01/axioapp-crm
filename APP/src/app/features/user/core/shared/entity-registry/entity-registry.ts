/**
 * Curated visual metadata for the six core CRM entities that Settings
 * pages present as pickers (custom fields, standard fields, and any
 * future entity-scoped settings surface).
 *
 * Icon + label + one-line description drive card-style pickers so every
 * page speaks the same visual language. Keyed by the backend's entity
 * value token (e.g. `contact`, `walk_in`), matching what
 * `standard_fields/registry.py` and `custom-fields-api.service`
 * exchange with the server.
 */

export interface EntityDescriptor {
  value: string;
  label: string;
  icon: string;
  description: string;
}

export const CORE_ENTITY_REGISTRY: ReadonlyArray<EntityDescriptor> = [
  {
    value: 'contact',
    label: 'Contacts',
    icon: 'users',
    description: 'People in your CRM',
  },
  {
    value: 'lead',
    label: 'Leads',
    icon: 'target',
    description: 'Sales opportunities',
  },
  {
    value: 'walk_in',
    label: 'Walk-ins',
    icon: 'footprints',
    description: 'In-store visits',
  },
  {
    value: 'appointment',
    label: 'Appointments',
    icon: 'calendar',
    description: 'Scheduled meetings',
  },
  {
    value: 'task',
    label: 'Tasks',
    icon: 'check-square',
    description: 'To-dos & follow-ups',
  },
  {
    value: 'catalog_item',
    label: 'Products',
    icon: 'package',
    description: 'Catalog items',
  },
];

/** Lookup by entity value. Falls back to a generic descriptor so unknown
 *  entities (e.g. newly-registered by a vertical pack that hasn't been
 *  added to the registry yet) still render a card instead of throwing. */
export function describeEntity(value: string): EntityDescriptor {
  const hit = CORE_ENTITY_REGISTRY.find((e) => e.value === value);
  if (hit) return hit;
  return {
    value,
    label: value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
    icon: 'square',
    description: '',
  };
}
