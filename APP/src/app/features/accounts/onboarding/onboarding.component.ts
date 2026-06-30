import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { startWith } from 'rxjs/operators';

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

  readonly selectedTemplateId = signal<string | null>(null);
  protected readonly selectedTile = computed<CatalogTile | null>(() => {
    const id = this.selectedTemplateId();
    if (!id) return null;
    return this.tiles().find((t) => t.template_id === id) ?? null;
  });

  // ── Wizard step state ──────────────────────────────────────────────
  // Zero-indexed: 0 = pick template, 1 = type org name, 2 = country /
  // currency / team size + submit. Form values + tile selection are
  // signals/FormGroup on the component instance, so going back and
  // forward between steps preserves everything the user already typed.
  readonly currentStep = signal<number>(0);
  readonly totalSteps = 3;
  protected readonly stepIndices = [0, 1, 2];

  readonly form = this.fb.group({
    organization_name: ['', [Validators.required, Validators.maxLength(100)]],
    country: ['India'],
    currency: [''],
    team_size: [''],
  });

  // The app runs zoneless change detection (provideZonelessChangeDetection
  // in app.config.ts), so reading `this.form.controls.<x>.value` directly
  // from a computed() does NOT subscribe the computed to form changes —
  // signals only depend on other signals. Bridge each form value we need
  // to gate UI on into a real signal via `toSignal` so the computeds
  // recompute when the user types.
  private readonly orgNameValue = toSignal(
    this.form.controls.organization_name.valueChanges.pipe(startWith('')),
    { initialValue: '' },
  );
  private readonly formStatusValue = toSignal(this.form.statusChanges, {
    initialValue: this.form.status,
  });

  protected readonly canSubmit = computed<boolean>(() => {
    return !!this.selectedTemplateId() && this.formStatusValue() === 'VALID';
  });

  // Per-step validity. Each step's Continue button is gated on its own
  // computed so the user can't advance until the relevant input is
  // filled. Driven from the bridged form signals above, so no state
  // lives outside the wizard.
  protected readonly canAdvanceStep1 = computed<boolean>(() => {
    return !!this.selectedTemplateId();
  });
  protected readonly canAdvanceStep2 = computed<boolean>(() => {
    const v = (this.orgNameValue() ?? '').toString().trim();
    return v.length > 0 && v.length <= 100;
  });
  protected readonly canAdvanceCurrent = computed<boolean>(() => {
    const step = this.currentStep();
    if (step === 0) return this.canAdvanceStep1();
    if (step === 1) return this.canAdvanceStep2();
    return this.canSubmit();
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
      this.catalogError.set('Could not load CRM templates. Please refresh and try again.');
    } finally {
      this.isLoadingCatalog.set(false);
    }
  }

  protected onTileSelect(templateId: string): void {
    this.selectedTemplateId.set(templateId);
    const tile = this.tiles().find((t) => t.template_id === templateId);
    if (tile) {
      // Pre-fill currency from the tile's pack default; user can still
      // override before submitting.
      this.form.patchValue({ currency: tile.default_currency });
    }
  }

  protected back(): void {
    const step = this.currentStep();
    if (step > 0) this.currentStep.set(step - 1);
  }

  async onSubmit(): Promise<void> {
    const step = this.currentStep();

    // Steps 1 and 2: the submit button is a "Continue →" that just
    // advances the wizard. The actual API call only fires on step 3.
    // Pressing Enter in an input on step 1 or 2 also hits ngSubmit —
    // which is the user expectation (Enter = advance). Gating by the
    // per-step validity here matches the button's disabled state.
    if (step === 0) {
      if (this.canAdvanceStep1()) this.currentStep.set(1);
      return;
    }
    if (step === 1) {
      if (this.canAdvanceStep2()) this.currentStep.set(2);
      return;
    }

    if (!this.canSubmit() || this.isSubmitting()) {
      this.form.markAllAsTouched();
      return;
    }
    const templateId = this.selectedTemplateId();
    if (!templateId) return;

    this.isSubmitting.set(true);
    const raw = this.form.getRawValue();
    try {
      await firstValueFrom(
        this.auth.completeOnboarding({
          organization_name: (raw.organization_name ?? '').trim(),
          template_id: templateId,
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
