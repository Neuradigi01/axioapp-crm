import { Injectable, inject, signal } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { AuthService } from './auth.service';
import { IUserDetails } from '@app/schemas/common';
import { ThemeService } from './theme.service';
import { AppSettings } from '@app/app.settings';

@Injectable({ providedIn: 'root' })
export class SharedService {
  readonly auth = inject(AuthService);
  readonly theme = inject(ThemeService);
  private readonly titleService = inject(Title);

  readonly pageTitle = signal('');

  get settings(): typeof AppSettings {
    return AppSettings;
  }

  get userDetails(): IUserDetails | null {
    return this.auth.getUserDetails();
  }

  get isLoggedIn(): boolean {
    return this.auth.isLoggedIn();
  }

  setPageTitle(title: string): void {
    this.pageTitle.set(title);
    this.titleService.setTitle(title);
  }
}
