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
import {
  FormArray,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

/**
 * Facebook Messenger / Instagram Direct sub-form for the central
 * template editor (Step 13).
 *
 * Meta's Messaging API is the same surface for both channels —
 * identical envelope, identical limits — so one sub-form serves
 * both. The editor wires this component for `channel in (facebook,
 * instagram)`. If Meta ever diverges them, split into two.
 *
 * Captures:
 *   - body text (1000-char Messenger limit)
 *   - up to 13 quick replies (20-char Messenger limit each — visible
 *     buttons under the message bubble that send a pre-canned
 *     payload back when tapped)
 *
 * Quick replies are stored on the body via the `__quick_replies`
 * tail JSON line so the central `body_text` column still holds
 * everything the editor needs (mirrors the SMS pattern of stashing
 * DLT metadata on a side table — for FB/IG we don't have an
 * extension table yet, so the tail line is the v1 plan; future
 * Messenger track may promote it).
 *
 * Future "structured message" types (generic template / button
 * template / list template) are explicitly out of scope — the
 * template-library track ships text-only Messenger surfaces only.
 */
const BODY_MAX = 1000;
const QUICK_REPLY_MAX_COUNT = 13;
const QUICK_REPLY_MAX_LENGTH = 20;

export type FbQuickReplyGroup = FormGroup<{
  text: FormControl<string>;
}>;

export type FbFormGroup = FormGroup<{
  body_text: FormControl<string>;
  quick_replies: FormArray<FbQuickReplyGroup>;
}>;


@Component({
  selector: 'app-fb-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule],
  templateUrl: './fb-form.component.html',
})
export class FbFormComponent {
  private readonly destroyRef = inject(DestroyRef);

  readonly form = input.required<FbFormGroup>();
  readonly disabled = input<boolean>(false);
  readonly trackFocus = input<(el: HTMLTextAreaElement | HTMLInputElement) => void>(
    () => undefined,
  );

  protected readonly BODY_MAX = BODY_MAX;
  protected readonly QUICK_REPLY_MAX_COUNT = QUICK_REPLY_MAX_COUNT;
  protected readonly QUICK_REPLY_MAX_LENGTH = QUICK_REPLY_MAX_LENGTH;

  private readonly bodyText = signal<string>('');

  constructor() {
    effect((onCleanup) => {
      const f = this.form();
      this.bodyText.set(f.controls.body_text.value);
      const sub = f.controls.body_text.valueChanges
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe((v) => this.bodyText.set(v ?? ''));
      onCleanup(() => sub.unsubscribe());
    });
  }

  protected readonly bodyLength = computed(() => this.bodyText().length);
  protected readonly canAddQuickReply = computed(
    () => this.quickReplies().length < QUICK_REPLY_MAX_COUNT,
  );

  protected quickReplies(): FormArray<FbQuickReplyGroup> {
    return this.form().controls.quick_replies;
  }

  protected addQuickReply(): void {
    if (!this.canAddQuickReply()) return;
    this.quickReplies().push(FbFormComponent.buildQuickReply(''));
  }

  protected removeQuickReply(index: number): void {
    this.quickReplies().removeAt(index);
  }

  protected onFocus(event: FocusEvent): void {
    const el = event.target as HTMLTextAreaElement | HTMLInputElement;
    this.trackFocus()(el);
  }

  static buildQuickReply(text: string): FbQuickReplyGroup {
    return new FormGroup({
      text: new FormControl<string>(text, {
        nonNullable: true,
        validators: [
          Validators.required,
          Validators.maxLength(QUICK_REPLY_MAX_LENGTH),
        ],
      }),
    });
  }

  static build(): FbFormGroup {
    return new FormGroup({
      body_text: new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.required, Validators.maxLength(BODY_MAX)],
      }),
      quick_replies: new FormArray<FbQuickReplyGroup>([]),
    });
  }
}
