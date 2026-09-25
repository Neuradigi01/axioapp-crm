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

// Palette design: soft pastel tint + theme-token text.
// The colored `bg-{color}-400/25` overlay is the owner-identity signal —
// picks the brighter -400 shade so the tint reads as a real pastel
// avatar colour (not a dark blob) in dark mode, and stays a soft
// coloured wash on white in light mode. Text uses the theme's
// `text-default / text-muted / text-faint` tokens so the title / body /
// caption hierarchy stays legible regardless of theme; coloring the
// text on top of a same-color translucent bg only worked on light mode
// and washed out in dark. `ring-{color}-400/40` gives the circle a
// clear coloured edge without shouting.
const PALETTE: ReadonlyArray<OwnerColor> = [
  {
    bg: 'bg-blue-400/25',
    text: 'text-default',
    ring: 'ring-blue-400/40',
    textMuted: 'text-muted',
    textFaint: 'text-faint',
  },
  {
    bg: 'bg-emerald-400/25',
    text: 'text-default',
    ring: 'ring-emerald-400/40',
    textMuted: 'text-muted',
    textFaint: 'text-faint',
  },
  {
    bg: 'bg-amber-400/25',
    text: 'text-default',
    ring: 'ring-amber-400/40',
    textMuted: 'text-muted',
    textFaint: 'text-faint',
  },
  {
    bg: 'bg-rose-400/25',
    text: 'text-default',
    ring: 'ring-rose-400/40',
    textMuted: 'text-muted',
    textFaint: 'text-faint',
  },
  {
    bg: 'bg-violet-400/25',
    text: 'text-default',
    ring: 'ring-violet-400/40',
    textMuted: 'text-muted',
    textFaint: 'text-faint',
  },
  {
    bg: 'bg-cyan-400/25',
    text: 'text-default',
    ring: 'ring-cyan-400/40',
    textMuted: 'text-muted',
    textFaint: 'text-faint',
  },
  {
    bg: 'bg-orange-400/25',
    text: 'text-default',
    ring: 'ring-orange-400/40',
    textMuted: 'text-muted',
    textFaint: 'text-faint',
  },
  {
    bg: 'bg-fuchsia-400/25',
    text: 'text-default',
    ring: 'ring-fuchsia-400/40',
    textMuted: 'text-muted',
    textFaint: 'text-faint',
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
