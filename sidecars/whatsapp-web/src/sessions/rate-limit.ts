export interface RateLimitAllow {
  ok: true;
}

export interface RateLimitDeny {
  ok: false;
  retry_after_ms: number;
}

export type RateLimitResult = RateLimitAllow | RateLimitDeny;

export interface RateLimitConfig {
  capacity: number;
  refillIntervalMs: number;
  now?: () => number;
}

interface BucketState {
  tokens: number;
  lastRefillMs: number;
}

export class TokenBucket {
  private readonly buckets = new Map<string, BucketState>();
  private readonly capacity: number;
  private readonly refillIntervalMs: number;
  private readonly now: () => number;

  constructor(cfg: RateLimitConfig) {
    this.capacity = cfg.capacity;
    this.refillIntervalMs = cfg.refillIntervalMs;
    this.now = cfg.now ?? Date.now;
  }

  acquire(key: string): RateLimitResult {
    const t = this.now();
    let bucket = this.buckets.get(key);
    if (!bucket) {
      bucket = { tokens: this.capacity, lastRefillMs: t };
      this.buckets.set(key, bucket);
    }

    const elapsed = t - bucket.lastRefillMs;
    if (elapsed >= this.refillIntervalMs) {
      const refills = Math.floor(elapsed / this.refillIntervalMs);
      bucket.tokens = Math.min(this.capacity, bucket.tokens + refills);
      bucket.lastRefillMs += refills * this.refillIntervalMs;
    }

    if (bucket.tokens <= 0) {
      const wait = this.refillIntervalMs - (t - bucket.lastRefillMs);
      return { ok: false, retry_after_ms: Math.max(0, wait) };
    }

    bucket.tokens -= 1;
    return { ok: true };
  }

  drop(key: string): void {
    this.buckets.delete(key);
  }
}

export const OUTBOUND_BUCKET_CAPACITY = 1;
export const OUTBOUND_REFILL_INTERVAL_MS = 1200;

export const outboundLimiter: TokenBucket = new TokenBucket({
  capacity: OUTBOUND_BUCKET_CAPACITY,
  refillIntervalMs: OUTBOUND_REFILL_INTERVAL_MS,
});
