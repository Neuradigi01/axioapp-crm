import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  EventEmitter,
  HostListener,
  Input,
  OnInit,
  Output,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { commonValidators } from '../shared/validators';
import { SavedRepliesStore } from '../conversations/saved-replies.store';
import { SavedReply } from '../conversations/conversations-api.service';
import { Review, ReviewsApiService } from './reviews-api.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Modal for replying to a review (or editing an existing reply). Shows
 * the original review for context, then the reply box with the team's
 * saved replies and an AI-drafted suggestion. On success the parent
 * receives the updated `Review` (status flipped to `replied`).
 */
@Component({
  selector: 'app-review-reply-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './reply-modal.component.html',
})
export class ReviewReplyModalComponent implements OnInit, AfterViewInit {
  private readonly api = inject(ReviewsApiService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly savedReplies = inject(SavedRepliesStore);

  @Input({ required: true }) review!: Review;

  @Output() readonly saved = new EventEmitter<Review>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly textControl = new FormControl('', {
    nonNullable: true,
    validators: [
      commonValidators.trimmedRequired,
      Validators.minLength(2),
      Validators.maxLength(4000),
    ],
  });

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);
  protected readonly suggesting = signal(false);
  protected readonly repliesOpen = signal(false);
  protected readonly repliesQuery = signal('');
  protected readonly repliesMatches = computed(() =>
    this.savedReplies.search(this.repliesQuery(), 8),
  );

  protected get isEdit(): boolean {
    return !!this.review.reply_text;
  }

  @ViewChild('replyBox') private readonly replyBox?: ElementRef<HTMLTextAreaElement>;

  ngOnInit(): void {
    if (this.review.reply_text) this.textControl.setValue(this.review.reply_text);
  }

  ngAfterViewInit(): void {
    this.replyBox?.nativeElement.focus();
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (this.repliesOpen()) this.repliesOpen.set(false);
    else this.close();
  }

  protected toggleReplies(): void {
    this.savedReplies.ensureLoaded();
    this.repliesQuery.set('');
    this.repliesOpen.update((v) => !v);
  }

  protected useSavedReply(reply: SavedReply): void {
    this.textControl.setValue(reply.body);
    this.textControl.markAsTouched();
    this.repliesOpen.set(false);
  }

  /** AI draft into the reply box — the operator reviews before sending. */
  protected suggest(): void {
    if (this.suggesting()) return;
    this.suggesting.set(true);
    this.submitError.set(null);
    this.api
      .suggestReply(this.review.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ text }) => {
          this.suggesting.set(false);
          this.textControl.setValue(text.slice(0, 4000));
          this.textControl.markAsTouched();
        },
        error: (err: HttpErrorResponse) => {
          this.suggesting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not draft a reply.');
        },
      });
  }

  protected submit(): void {
    if (!this.textControl.valid) {
      this.textControl.markAsTouched();
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .reply(this.review.id, this.textControl.value.trim())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.submitting.set(false);
          this.saved.emit(updated);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not send reply.');
        },
      });
  }

  protected close(): void {
    if (this.submitting()) return;
    this.cancel.emit();
  }

  protected stars(n: number): string {
    return '★★★★★'.slice(0, n) + '☆☆☆☆☆'.slice(0, 5 - n);
  }
}
