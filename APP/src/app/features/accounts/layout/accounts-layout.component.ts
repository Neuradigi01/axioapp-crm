import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

/**
 * Wrapper for every ``/accounts/*`` page (login, register, forgot /
 * reset password, 2FA, verify-email, email-verification-notice,
 * accept-invite).
 *
 * Theme handling: accounts pages inherit whatever theme the user
 * has picked (light / dark / system). Every child page is built
 * from semantic tokens (``bg-surface``, ``border-subtle``,
 * ``text-default``) so both palettes render correctly with zero
 * per-page style change. If the browser needs native form control
 * hints (autofill background, scrollbar), those inherit from
 * ``color-scheme`` set at the ``<html>`` level by the ThemeService.
 */
@Component({
  selector: 'app-accounts-layout',
  templateUrl: './accounts-layout.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet],
})
export class AccountsLayoutComponent {}
