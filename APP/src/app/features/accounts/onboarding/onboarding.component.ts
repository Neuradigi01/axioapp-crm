import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';

import { FurnitureAuthService } from '@app/features/user/core/auth/auth.service';
import { SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import { OnboardingApiService } from './onboarding-api.service';
import { PackTileComponent } from './pack-tile.component';
import { CatalogTile } from './onboarding.types';

const TEAM_SIZES = ['1-5', '6-20', '21-50', '51-200', '200+'] as const;

@Component({
  selector: 'app-onboarding',
  templateUrl: './onboarding.component.html',
  styleUrl: './onboarding.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, PackTileComponent],
})
export class OnboardingComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(OnboardingApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);

  readonly teamSizes = TEAM_SIZES;

  readonly tiles = signal<CatalogTile[]>([]);
  readonly isLoadingCatalog = signal<boolean>(true);
  readonly catalogError = signal<string | null>(null);
  readonly isSubmitting = signal<boolean>(false);

  readonly selectedPackId = signal<string | null>(null);
  protected readonly selectedTile = computed<CatalogTile | null>(() => {
    const id = this.selectedPackId();
    if (!id) return null;
    return this.tiles().find((t) => t.pack_id === id) ?? null;
  });

  readonly form = this.fb.group({
    organization_name: ['', [Validators.required, Validators.maxLength(100)]],
    country: ['India'],
    currency: [''],
    team_size: [''],
  });

  protected readonly canSubmit = computed<boolean>(() => {
    return !!this.selectedPackId() && this.form.valid;
  });

  async ngOnInit(): Promise<void> {
    // Defensive: an unauthenticated visitor reaching /onboarding can't
    // complete it (the POST 401s). Bounce them to login rather than
    // letting the page render an unreachable form.
    if (!this.auth.isAuthenticated()) {
      await this.router.navigateByUrl('/accounts/login');
      return;
    }

    try {
      const res = await firstValueFrom(this.api.getCatalog());
      this.tiles.set(res.packs);
    } catch {
      this.catalogError.set(
        'Could not load CRM templates. Please refresh and try again.',
      );
    } finally {
      this.isLoadingCatalog.set(false);
    }
  }

  protected onTileSelect(packId: string): void {
    this.selectedPackId.set(packId);
    const tile = this.tiles().find((t) => t.pack_id === packId);
    if (tile) {
      // Pre-fill currency from the tile's pack default; user can still
      // override before submitting.
      this.form.patchValue({ currency: tile.default_currency });
    }
  }

  async onSubmit(): Promise<void> {
    if (!this.canSubmit() || this.isSubmitting()) {
      this.form.markAllAsTouched();
      return;
    }
    const packId = this.selectedPackId();
    if (!packId) return;

    this.isSubmitting.set(true);
    const raw = this.form.getRawValue();
    try {
      await firstValueFrom(
        this.auth.completeOnboarding({
          organization_name: (raw.organization_name ?? '').trim(),
          pack_id: packId,
          country: raw.country || null,
          currency: raw.currency || null,
          team_size: raw.team_size || null,
        }),
      );
      await this.router.navigateByUrl('/user');
    } catch (err: unknown) {
      const detail = (err as { error?: { detail?: unknown } })?.error?.detail;
      let msg = 'Could not finish setup. Please try again.';
      if (typeof detail === 'string') {
        msg = detail;
      } else if (
        detail &&
        typeof detail === 'object' &&
        'message' in (detail as Record<string, unknown>)
      ) {
        msg = String((detail as Record<string, unknown>)['message']);
      }
      this.snackBar.open(msg, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isSubmitting.set(false);
    }
  }
}
