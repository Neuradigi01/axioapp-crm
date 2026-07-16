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
  darkMode: ['class', '.dark-theme'],
  theme: {
    extend: {},
  },
  plugins: [],
};
