import { logger } from "../logger.js";

export type RetryTask = () => Promise<void>;

export interface RetryQueueConfig {
  backoffMs: number[];
  setTimer?: (cb: () => void, ms: number) => { ref: () => void; unref: () => void };
  label?: string;
}

interface QueuedItem {
  id: number;
  task: RetryTask;
  attempt: number;
  description?: string;
}

const DEFAULT_BACKOFFS_MS = [1_000, 5_000, 30_000, 120_000, 600_000];

export class RetryQueue {
  private readonly backoffs: number[];
  private readonly label: string;
  private readonly setTimer: NonNullable<RetryQueueConfig["setTimer"]>;
  private nextId = 1;
  private pendingTimers = new Set<{ ref: () => void; unref: () => void }>();

  constructor(cfg: RetryQueueConfig = { backoffMs: DEFAULT_BACKOFFS_MS }) {
    this.backoffs = cfg.backoffMs.length > 0 ? cfg.backoffMs : DEFAULT_BACKOFFS_MS;
    this.label = cfg.label ?? "retry-queue";
    this.setTimer =
      cfg.setTimer ??
      ((cb, ms) => {
        const t = setTimeout(cb, ms);
        return { ref: () => t.ref(), unref: () => t.unref() };
      });
  }

  enqueue(task: RetryTask, description?: string): void {
    this.scheduleAttempt({ id: this.nextId++, task, attempt: 0, description });
  }

  private scheduleAttempt(item: QueuedItem): void {
    const delay = this.backoffs[item.attempt] ?? this.backoffs[this.backoffs.length - 1]!;
    const handle = this.setTimer(() => {
      this.pendingTimers.delete(handle);
      void this.run(item);
    }, delay);
    handle.unref();
    this.pendingTimers.add(handle);
  }

  private async run(item: QueuedItem): Promise<void> {
    try {
      await item.task();
    } catch (err) {
      const next = item.attempt + 1;
      if (next >= this.backoffs.length) {
        logger.error(
          { err, attempts: next, description: item.description, queue: this.label },
          "retry-queue.dropped",
        );
        return;
      }
      logger.warn(
        {
          err,
          attempt: next,
          nextDelayMs: this.backoffs[next] ?? this.backoffs[this.backoffs.length - 1],
          description: item.description,
          queue: this.label,
        },
        "retry-queue.retry",
      );
      this.scheduleAttempt({ ...item, attempt: next });
    }
  }

  pendingCount(): number {
    return this.pendingTimers.size;
  }
}
