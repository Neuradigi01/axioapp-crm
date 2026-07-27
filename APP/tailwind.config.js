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
  // Class-based dark mode wired to the app's existing theme service
  // (`body.dark-theme` is toggled by `ThemeService`, see
  // core/services/theme.service.ts). Lets `dark:` variants on Tailwind
  // classes activate exactly when the in-app theme toggle flips —
  // not the OS-level `prefers-color-scheme` (the default).
  // Step 2 of the design refresh will switch this to
  // `['selector', '[data-theme="dark"]']`; keeping the class selector
  // here so this step is additive-only.
  darkMode: ['class', '.dark-theme'],
  theme: {
    extend: {
      // AIXO semantic colors — resolve from CSS variables defined in
      // src/styles/aixo-tokens.scss. Use `bg-surface`, `text-muted`,
      // `border-subtle`, `bg-accent`, `bg-accent-soft`, `text-accent`
      // in place of raw palette utilities (`bg-white`, `text-zinc-500`).
      colors: {
        app: 'var(--bg)',
        surface: 'var(--surface)',
        'surface-2': 'var(--surface-2)',
        subtle: 'var(--border)',
        default: 'var(--text)',
        muted: 'var(--text-muted)',
        faint: 'var(--text-faint)',
        accent: 'var(--accent)',
        'accent-soft': 'var(--accent-soft)',
      },
      borderColor: {
        subtle: 'var(--border)',
      },
      fontFamily: {
        ui: [
          'Inter Variable',
          'Inter',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'sans-serif',
        ],
        display: [
          'Inter Tight Variable',
          'Inter Tight',
          'Inter Variable',
          'Inter',
          'system-ui',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono Variable',
          'JetBrains Mono',
          'ui-monospace',
          'SF Mono',
          'Consolas',
          'monospace',
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
