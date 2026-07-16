import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

/**
 * Push notification sub-form for the central template editor (Step 13).
 *
 * Captures:
 *   - title (50-char limit — the upper bound iOS/Android still render
 *     without truncation on a typical lock screen)
 *   - body (240-char limit — same constraint)
 *   - action URL / deeplink (optional; tapping the notification opens
 *     this in the operator's web app or routes to the deeplinked
 *     screen in a future native app)
 *
 * Title is stored on the central template's `subject` column (which
 * is otherwise email-only — repurposed per the models docstring).
 * Body is the usual `body_text`. The deeplink is stashed on the body
 * via the existing trailing convention (templates have no push
 * extension table yet; promote when a real provider lands).
 *
 * There is no external approval workflow for push templates —
 * `external_status` stays `n_a` always.
 */
const TITLE_MAX = 50;
const BODY_MAX = 240;
const URL_MAX = 2048;

export type PushFormGroup = FormGroup<{
  title: FormControl<string>;
  body_text: FormControl<string>;
  action_url: FormControl<string>;
}>;

@Component({
  selector: 'app-push-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './push-form.component.html',
})
export class PushFormComponent {
  private readonly destroyRef = inject(DestroyRef);

  readonly form = input.required<PushFormGroup>();
  readonly disabled = input<boolean>(false);
  readonly trackFocus = input<(el: HTMLTextAreaElement | HTMLInputElement) => void>(
    () => undefined,
  );

  protected readonly TITLE_MAX = TITLE_MAX;
  protected readonly BODY_MAX = BODY_MAX;
  protected readonly URL_MAX = URL_MAX;

  private readonly title = signal<string>('');
  private readonly bodyText = signal<string>('');

  constructor() {
    effect((onCleanup) => {
      const f = this.form();
      this.title.set(f.controls.title.value);
      this.bodyText.set(f.controls.body_text.value);
      const subTitle = f.controls.title.valueChanges
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((v) => this.title.set(v ?? ''));
      const subBody = f.controls.body_text.valueChanges
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((v) => this.bodyText.set(v ?? ''));
      onCleanup(() => {
        subTitle.unsubscribe();
        subBody.unsubscribe();
      });
    });
  }

  protected readonly titleLength = computed(() => this.title().length);
  protected readonly bodyLength = computed(() => this.bodyText().length);

  protected onFocus(event: FocusEvent): void {
    const el = event.target as HTMLTextAreaElement | HTMLInputElement;
    this.trackFocus()(el);
  }

  static build(): PushFormGroup {
    return new FormGroup({
      title: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.required, Validators.maxLength(TITLE_MAX)],
      }),
      body_text: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.required, Validators.maxLength(BODY_MAX)],
      }),
      action_url: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.maxLength(URL_MAX)],
      }),
    });
  }
}
