import { ChangeDetectionStrategy, Component, OnDestroy, OnInit } from '@angular/core';
import { RouterOutlet } from '@angular/router';

/**
 * Wrapper for every ``/accounts/*`` page (login, register, forgot /
 * reset password, 2FA, verify-email, email-verification-notice,
 * accept-invite).
 *
 * Theme handling: the accounts surface is intentionally
 * ``color-scheme: light`` — no theme toggle here, matching the
 * memory note "the accounts-layout theme toggle was removed (the
 * user app is light-only with no toggle)". But the CSS-var driven
 * Tailwind utilities on the child pages (``bg-surface-2``,
 * ``border-subtle``, ``text-default``, ``bg-accent``) resolve to
 * whatever ``[data-theme]`` on ``<html>`` says — which is whatever
 * the user last set inside the ``/user/*`` app. Without pinning,
 * navigating from a dark-mode dashboard to the accept-invite page
 * would render mismatched: light widgets (from ``color-scheme``)
 * against dark surface tokens (from ``[data-theme='dark']``).
 *
 * On mount we pin ``[data-theme='light']`` so accounts pages use
 * the same light-mode tokens the ``/user/*`` app uses in light
 * mode — visual match with zero per-page style change. On destroy
 * we restore the prior attribute so returning to a dark ``/user/*``
 * page keeps its dark palette.
 */
@Component({
  selector: 'app-accounts-layout',
  templateUrl: './accounts-layout.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet],
})
export class AccountsLayoutComponent implements OnInit, OnDestroy {
  private previousTheme: string | null = null;

  ngOnInit(): void {
    if (typeof document === 'undefined') return;
    this.previousTheme = document.documentElement.getAttribute('data-theme');
    document.documentElement.setAttribute('data-theme', 'light');
  }

  ngOnDestroy(): void {
    if (typeof document === 'undefined') return;
    if (this.previousTheme === null) {
      document.documentElement.removeAttribute('data-theme');
    } else {
      document.documentElement.setAttribute('data-theme', this.previousTheme);
    }
  }
}
