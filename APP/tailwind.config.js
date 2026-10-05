/**
 * CSS-variable colour that still honours Tailwind's opacity modifier.
 * A plain `'var(--accent)'` silently drops `/NN` utilities
 * (`bg-accent/20`, `ring-accent/25`, `bg-surface/90` never got
 * generated). With a literal opacity we mix the variable toward
 * transparent; without one (plain `bg-accent`, where Tailwind passes
 * its own `var(--tw-…-opacity)`), the output is the bare variable,
 * exactly as before.
 */
const token =
  (name) =>
  ({ opacityValue }) =>
    opacityValue === undefined || String(opacityValue).startsWith('var(')
      ? `var(${name})`
      : `color-mix(in srgb, var(${name}) calc(${opacityValue} * 100%), transparent)`;

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/app/features/user/**/*.{html,ts}',
    // Onboarding page is Tailwind-only (per CLAUDE.md) but lives under
    // `accounts/` because it's part of the signup funnel. Scan it here
    // so utility classes unique to that page (e.g. `bg-white`,
    // `border-gray-300`) actually land in the bundle.
    './src/app/features/accounts/onboarding/**/*.{html,ts}',
    './src/app/staff-portal/**/*.{html,ts}',
  ],
  // Attribute-based dark mode. `[data-theme="dark"]` is set on <html> by
  // `ThemeService` (core/services/theme.service.ts) and by the inline
  // pre-hydration script in index.html. `dark:` variants activate
  // whenever the AIXO token layer flips dark — the two mechanisms share
  // the same trigger, so tokens and Tailwind stay in lockstep.
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      // AIXO semantic colors — resolve from CSS variables defined in
      // src/styles/aixo-tokens.scss. Use `bg-surface`, `text-muted`,
      // `border-subtle`, `bg-accent`, `bg-accent-soft`, `text-accent`
      // in place of raw palette utilities (`bg-white`, `text-zinc-500`).
      colors: {
        app: token('--bg'),
        surface: token('--surface'),
        'surface-2': token('--surface-2'),
        subtle: token('--border'),
        default: token('--text'),
        muted: token('--text-muted'),
        faint: token('--text-faint'),
        accent: token('--accent'),
        'accent-soft': token('--accent-soft'),
      },
      borderColor: {
        subtle: token('--border'),
        muted: token('--text-muted'),
        accent: token('--accent'),
      },
      ringColor: {
        accent: token('--accent'),
        subtle: token('--border'),
      },
      fontFamily: {
        // Emoji fonts are appended to every family so inline emojis
        // (🛋 🎉 🔒 etc.) render on OS emoji fallbacks instead of tofu.
        ui: [
          'Inter Variable',
          'Inter',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'sans-serif',
          'Apple Color Emoji',
          'Segoe UI Emoji',
          'Segoe UI Symbol',
          'Noto Color Emoji',
        ],
        display: [
          'Inter Tight Variable',
          'Inter Tight',
          'Inter Variable',
          'Inter',
          'system-ui',
          'sans-serif',
          'Apple Color Emoji',
          'Segoe UI Emoji',
          'Segoe UI Symbol',
          'Noto Color Emoji',
        ],
        mono: [
          'JetBrains Mono Variable',
          'JetBrains Mono',
          'ui-monospace',
          'SF Mono',
          'Consolas',
          'monospace',
          'Apple Color Emoji',
          'Segoe UI Emoji',
          'Segoe UI Symbol',
          'Noto Color Emoji',
        ],
      },
      boxShadow: {
        elevated: '0 12px 32px rgba(0, 0, 0, 0.35)',
        card: '0 1px 2px rgba(0, 0, 0, 0.06), 0 0 0 1px var(--border)',
      },
      borderRadius: {
        xl: '12px',
        '2xl': '14px',
      },
    },
  },
  plugins: [],
};
