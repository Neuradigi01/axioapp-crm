import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { forkJoin } from 'rxjs';

import { Task, TasksApiService } from '../tasks/tasks-api.service';
import { ChannelBrandIconComponent } from './channel-brand-icon.component';
import { Conversation, ConversationsApiService } from './conversations-api.service';

/**
 * Details-rail context for the linked contact: their open follow-up
 * tasks and every other conversation with them (e.g. the email thread
 * next to this WhatsApp chat). Both load in parallel whenever the
 * contact changes; clicking another conversation opens it in place.
 */
@Component({
  selector: 'app-contact-activity',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, RouterLink, ChannelBrandIconComponent],
  template: `
    @if (loading()) {
      <div class="space-y-1.5" aria-hidden="true">
        <div class="h-3 w-1/2 animate-pulse rounded bg-surface-2"></div>
        <div class="h-3 w-3/4 animate-pulse rounded bg-surface-2"></div>
      </div>
    } @else if (error()) {
      <p class="text-[11px] text-muted">{{ error() }}</p>
    } @else {
      <section class="flex flex-col gap-1.5">
        <p class="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted">
          Open tasks
          @if (taskTotal() > 0) {
            <span class="ml-1 rounded-full bg-surface-2 px-1.5 py-0.5 text-[10px] text-default">
              {{ taskTotal() }}
            </span>
          }
        </p>
        @if (tasks().length === 0) {
          <p class="text-[11px] text-faint">No open tasks for this contact.</p>
        }
        @for (t of tasks(); track t.id) {
          <a
            [routerLink]="['/user/contacts', contactId()]"
            class="flex items-start gap-1.5 rounded-md px-1 py-0.5 text-xs text-default transition hover:bg-surface-2"
          >
            <lucide-icon name="circle-dot" class="mt-0.5 h-3 w-3 shrink-0 text-muted" />
            <span class="min-w-0 flex-1">
              <span class="block truncate">{{ t.title }}</span>
              @if (t.due_at) {
                <span
                  [class]="'block text-[10.5px] ' + (isOverdue(t) ? 'text-red-500' : 'text-muted')"
                >
                  {{ isOverdue(t) ? 'Overdue · ' : 'Due ' }}{{ formatDate(t.due_at) }}
                </span>
              }
            </span>
          </a>
        }
      </section>

      @if (otherConversations().length > 0) {
        <section class="mt-3 flex flex-col gap-1.5">
          <p class="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted">
            Other conversations
          </p>
          @for (c of otherConversations(); track c.id) {
            <button
              type="button"
              (click)="openConversation.emit(c.id)"
              class="flex items-center gap-2 rounded-md px-1 py-1 text-left text-xs text-default transition hover:bg-surface-2"
            >
              <span
                class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-2 text-muted"
              >
                <app-channel-brand-icon [channel]="c.channel" class="h-3 w-3" />
              </span>
              <span class="min-w-0 flex-1">
                <span class="block truncate capitalize">{{ c.channel }} · {{ c.status }}</span>
                <span class="block truncate text-[10.5px] text-muted">
                  {{ c.last_message_body || c.external_id }}
                </span>
              </span>
              @if (c.unread_count > 0) {
                <span class="rounded-full bg-red-500 px-1.5 text-[9.5px] font-semibold text-white">
                  {{ c.unread_count }}
                </span>
              }
            </button>
          }
        </section>
      }
    }
  `,
})
export class ContactActivityComponent {
  private readonly tasksApi = inject(TasksApiService);
  private readonly conversationsApi = inject(ConversationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly contactId = input.required<string>();
  /** The open conversation — excluded from "Other conversations". */
  readonly conversationId = input.required<string>();
  readonly openConversation = output<string>();

  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly tasks = signal<Task[]>([]);
  protected readonly taskTotal = signal(0);
  private readonly contactConversations = signal<Conversation[]>([]);

  protected readonly otherConversations = computed(() =>
    this.contactConversations().filter((c) => c.id !== this.conversationId()),
  );

  private static readonly MAX_TASKS = 5;

  constructor() {
    effect(() => this.load(this.contactId()));
  }

  protected isOverdue(t: Task): boolean {
    return !!t.due_at && new Date(t.due_at).getTime() < Date.now();
  }

  protected formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short' });
  }

  private load(contactId: string): void {
    this.loading.set(true);
    this.error.set(null);
    forkJoin({
      tasks: this.tasksApi.listForEntity('contact', contactId, 'open'),
      conversations: this.conversationsApi.list({ contact_id: contactId, size: 10 }),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ tasks, conversations }) => {
          // Contact switched while in flight — drop the stale result.
          if (this.contactId() !== contactId) return;
          this.tasks.set(tasks.items.slice(0, ContactActivityComponent.MAX_TASKS));
          this.taskTotal.set(tasks.total);
          this.contactConversations.set(conversations.items);
          this.loading.set(false);
        },
        error: (_err: HttpErrorResponse) => {
          if (this.contactId() !== contactId) return;
          this.loading.set(false);
          this.error.set('Could not load contact activity.');
        },
      });
  }
}
