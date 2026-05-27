/**
 * Deterministic owner-colour palette.
 *
 * Given a user id (UUID), returns a `{ bg, text, ring }` Tailwind
 * class triple. The same user id always maps to the same colour so an
 * "owner" tag on contacts/leads/appointments stays recognisable across
 * pages and refreshes. `null` / `undefined` / empty string returns the
 * neutral zinc set for the "unassigned" case.
 *
 * Re-usable across contacts list, lead cards, appointments calendar —
 * anywhere an owner avatar wants a colour.
 */

export interface OwnerColor {
  bg: string;
  text: string;
  ring: string;
}

const PALETTE: ReadonlyArray<OwnerColor> = [
  { bg: 'bg-blue-100', text: 'text-blue-800', ring: 'ring-blue-200' },
  { bg: 'bg-emerald-100', text: 'text-emerald-800', ring: 'ring-emerald-200' },
  { bg: 'bg-amber-100', text: 'text-amber-800', ring: 'ring-amber-200' },
  { bg: 'bg-rose-100', text: 'text-rose-800', ring: 'ring-rose-200' },
  { bg: 'bg-violet-100', text: 'text-violet-800', ring: 'ring-violet-200' },
  { bg: 'bg-cyan-100', text: 'text-cyan-800', ring: 'ring-cyan-200' },
  { bg: 'bg-orange-100', text: 'text-orange-800', ring: 'ring-orange-200' },
  { bg: 'bg-fuchsia-100', text: 'text-fuchsia-800', ring: 'ring-fuchsia-200' },
];

const UNASSIGNED: OwnerColor = {
  bg: 'bg-zinc-100',
  text: 'text-zinc-600',
  ring: 'ring-zinc-200',
};

export function ownerColor(userId: string | null | undefined): OwnerColor {
  if (!userId) return UNASSIGNED;
  // djb2-style hash into the palette index — deterministic per user id.
  let h = 0;
  for (let i = 0; i < userId.length; i++) {
    h = ((h << 5) - h + userId.charCodeAt(i)) | 0;
  }
  return PALETTE[Math.abs(h) % PALETTE.length];
}
