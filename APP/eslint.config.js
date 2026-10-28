// @ts-check
// Flat ESLint config for the Core CRM Angular app (Angular 21 / angular-eslint 21
// / typescript-eslint 8 / eslint 9). Staged enforcement — see CLAUDE.md:
//   errors  -> BLOCKING (pre-commit hook + CI)
//   warn    -> reported, not blocking yet (documented "promote after cleanup")
const eslint = require('@eslint/js');
const tseslint = require('typescript-eslint');
const angular = require('angular-eslint');

module.exports = tseslint.config(
  {
    // Global ignores (this object has ONLY `ignores`, so it applies globally).
    ignores: [
      'dist/**',
      '.angular/**',
      'node_modules/**',
      'coverage/**',
      'scripts/**',
      // Legacy template admin panel — UNTOUCHED per CLAUDE.md. Do not lint/format.
      'src/app/features/admin/**',
      // Generated from the OpenAPI schema (openapi-typescript) — not hand-written.
      'src/app/features/user/core/shared/api-types/**',
    ],
  },
  {
    files: ['**/*.ts'],
    extends: [
      eslint.configs.recommended,
      ...tseslint.configs.recommended,
      ...angular.configs.tsRecommended,
    ],
    processor: angular.processInlineTemplates,
    rules: {
      // Blocking, but allow the conventional `_`-prefix opt-out for intentionally
      // unused args / caught errors / vars.
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
          // Allow the `const { drop, ...rest } = x` field-omission idiom.
          ignoreRestSiblings: true,
        },
      ],
      // Promote to error once the constructor-DI -> inject() migration is done.
      '@angular-eslint/prefer-inject': 'warn',
      // The autofix is a breaking @Output() rename — keep as warn for now.
      '@angular-eslint/no-output-native': 'warn',
    },
  },
  {
    files: ['**/*.html'],
    extends: [...angular.configs.templateRecommended, ...angular.configs.templateAccessibility],
    rules: {
      // Allow the intentional `x == null` (null-or-undefined) idiom; flag other `==`.
      '@angular-eslint/template/eqeqeq': ['error', { allowNullOrUndefined: true }],
      // Real accessibility debt — reported, not blocking yet.
      // Promote to error after the a11y cleanup pass.
      '@angular-eslint/template/click-events-have-key-events': 'warn',
      '@angular-eslint/template/interactive-supports-focus': 'warn',
      '@angular-eslint/template/label-has-associated-control': 'warn',
      '@angular-eslint/template/no-autofocus': 'warn',
    },
  }
);
