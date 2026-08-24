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
  /** Body-copy text tone that reads well on `bg`. `text` above is the
   *  strong / title tone; this is the secondary tone (line 2 / meta).
   *  On pastel backgrounds we go a hue-shade below the title (700 vs
   *  800) so it reads as "muted within the card" rather than the
   *  theme-wide `text-muted` which is designed for the dark surface
   *  and disappears on pastels. */
  textMuted: string;
  /** Faint / caption text tone (owner label footer, dot separator).
   *  A hue-shade lower still (600 vs 700) so the visual hierarchy
   *  title > body > caption is preserved on the card. */
  textFaint: string;
}

const PALETTE: ReadonlyArray<OwnerColor> = [
  {
    bg: 'bg-blue-100',
    text: 'text-blue-800',
    ring: 'ring-blue-200',
    textMuted: 'text-blue-700',
    textFaint: 'text-blue-600',
  },
  {
    bg: 'bg-emerald-100',
    text: 'text-emerald-800',
    ring: 'ring-emerald-200',
    textMuted: 'text-emerald-700',
    textFaint: 'text-emerald-600',
  },
  {
    bg: 'bg-amber-100',
    text: 'text-amber-800',
    ring: 'ring-amber-200',
    textMuted: 'text-amber-700',
    textFaint: 'text-amber-600',
  },
  // The red set uses a translucent bg (red-500/10) so it already sits
  // well on dark theme with the app's default text tokens — keep the
  // theme-wide muted / faint colours here rather than red-700/600
  // (which would clash with the semi-transparent background).
  {
    bg: 'bg-red-500/10',
    text: 'text-red-400',
    ring: 'ring-red-500/20',
    textMuted: 'text-muted',
    textFaint: 'text-faint',
  },
  {
    bg: 'bg-violet-100',
    text: 'text-violet-800',
    ring: 'ring-violet-200',
    textMuted: 'text-violet-700',
    textFaint: 'text-violet-600',
  },
  {
    bg: 'bg-cyan-100',
    text: 'text-cyan-800',
    ring: 'ring-cyan-200',
    textMuted: 'text-cyan-700',
    textFaint: 'text-cyan-600',
  },
  {
    bg: 'bg-orange-100',
    text: 'text-orange-800',
    ring: 'ring-orange-200',
    textMuted: 'text-orange-700',
    textFaint: 'text-orange-600',
  },
  {
    bg: 'bg-fuchsia-100',
    text: 'text-fuchsia-800',
    ring: 'ring-fuchsia-200',
    textMuted: 'text-fuchsia-700',
    textFaint: 'text-fuchsia-600',
  },
];

const UNASSIGNED: OwnerColor = {
  bg: 'bg-surface-2',
  text: 'text-muted',
  ring: 'border-subtle',
  textMuted: 'text-muted',
  textFaint: 'text-faint',
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

/**
 * Two-letter initials from a full name. Returns the first letter of
 * the first two whitespace-separated words, uppercased. Falls back to
 * `?` when the name is empty / nullish. Use alongside `ownerColor` to
 * render a staff avatar circle anywhere in the UI.
 */
export function staffInitials(fullName: string | null | undefined): string {
  if (!fullName) return '?';
  const parts = fullName
    .trim()
    .split(/\s+/)
    .filter((p) => p.length > 0);
  if (parts.length === 0) return '?';
  return parts
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('');
}
